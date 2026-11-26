"""End-to-end HTTP/SQLite checks; only Claude's paid generation is substituted."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))
from test_module1 import sample, Running, http, create_server as create_web
from module1.module1_core import Module1
from module2.bridge import planner_payload
from module2.catalog import load_catalog
from module2.contract import validate_contract, ContractError
from module2.llm import ClaudePlanLLM
from module2.server import create_server as create_planner
from module2.service import PlanService, ServiceError
from module2.tests.test_planner import ScriptedLLM
from module2.tests.fixtures import valid_plan


def envelope(**updates):
    engine = Module1()
    result, _ = engine.evaluate(sample(**updates))
    return engine.envelope(result, "integration-test")


def neutral_plan():
    plan = valid_plan()
    plan["summary"] = "현재 수준을 유지하고 군장 훈련을 준비하는 보완 운동 계획입니다."
    for row in plan["rows"]:
        row["reason"] = row["reason"].replace("팔굽혀펴기 16회 증가를 위해", "상체 지구력을 위해").replace("윗몸일으키기 18회 증가를 위해", "몸통 지구력을 위해").replace("3km 148초 단축을 위해", "유산소 체력을 위해")
    return plan


@pytest.mark.parametrize("age,current,directions,amounts", [
    (23, (48, 60, 960), ["increase", "increase", "decrease"], [16, 18, 148]),
    (23, (90, 100, 700), ["maintain"] * 3, [0, 0, 0]),
    (26, (90, 60, 700), ["maintain", "increase", "maintain"], [0, 16, 0]),
    (29, (62, 76, 832), ["met"] * 3, [0, 0, 0]),
])
def test_signed_goals_and_needs(age, current, directions, amounts):
    body = envelope(age=age, **dict(zip(("pushups_2min", "situps_2min", "run_3km_seconds"), current)))
    raw = planner_payload(body)
    pi = validate_contract(raw, load_catalog())
    assert [n.direction for n in pi.needs] == directions
    assert [n.amount for n in pi.needs] == amounts
    assert raw["difference_matrix"] == body["module1_result"]["difference_matrix"]


def test_every_seed_record_is_accepted_by_module2():
    engine, catalog = Module1(), load_catalog()
    rows = json.loads((ROOT / "backend/module1/data/synthetic_soldiers.json").read_text(encoding="utf-8"))
    assert len(rows) == 1000
    for row in rows:
        result, _ = engine.evaluate(row)
        validate_contract(planner_payload(engine.envelope(result, row["soldier_id"]), engine), catalog)


def test_rejects_old_goal_and_changed_catalog_before_llm():
    llm = ScriptedLLM([])
    service = PlanService(lambda: llm)
    body = envelope(pushups_2min=90, situps_2min=100, run_3km_seconds=700)
    p = body["module1_result"]
    p["goal_records"] = copy.deepcopy(p["current_records"])
    p["goal_matrix"] = copy.deepcopy(p["now_matrix"])
    p["difference_matrix"] = [[0, 0, 0, 0]]
    with pytest.raises(ServiceError) as error:
        service.submit(body)
    assert error.value.http_status == 422 and not llm.calls
    body = envelope()
    body["shared_resources"]["exercise_catalog"]["exercises"][0]["name"] = "different"
    with pytest.raises(ServiceError):
        service.submit(body)
    assert not llm.calls


def test_missing_key_is_explicit_and_health_still_works(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("module2.llm.ENV_FILE", tmp_path / "missing.env")
    with Running(create_planner(port=0)) as api:
        code, health = http(api.base, "/health")
        assert code == 200 and health["mode"] == "real" and not health["generation_ready"]
        code, response = http(api.base, "/api/v1/plans", envelope())
        assert code == 503 and response["error"]["code"] == "api_key_missing"


@pytest.mark.parametrize("above", [False, True])
def test_web_to_real_module2_and_persistence(tmp_path, above):
    llm = ScriptedLLM([neutral_plan() if above else valid_plan()])
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([sample(soldier_id="22-00000002")]), encoding="utf-8")
    db = tmp_path / "test.sqlite3"
    with Running(create_planner(port=0, service=PlanService(lambda: llm))) as planner:
        with Running(create_web(db, seed, planner.base, port=0)) as web:
            updates = dict(pushups_2min=90, situps_2min=100, run_3km_seconds=700) if above else {}
            assert http(web.base, "/api/v1/soldiers", sample(**updates))[0] == 201
            code, body = http(web.base, "/api/v1/soldiers/22-00000001/module2", {})
            assert code == 200
            response = body["module2_response"]
            assert response["generation_status"] == "passed"
            assert len(response["result"]["plan"]) == 46
            assert len(llm.calls) == 1
            assert "보병 소총수" in llm.calls[0]["system"]
            assert "검정 종목 반복만으로 계획을 채우지 않습니다" in llm.calls[0]["system"]
            assert {r["week"] for r in response["plan"]} == set(range(1, 9))
            assert http(web.base, "/api/v1/soldiers/22-00000001")[1]["latest_plan"] == response
        with Running(create_web(db, seed, planner.base, port=0)) as reopened:
            stored = http(reopened.base, "/api/v1/soldiers/22-00000001")[1]
            assert stored["latest_plan"] == response
            assert stored["result"]["goal_records"] == stored["result"]["reference_records"]


def test_failed_plan_stays_failed_after_two_revisions():
    bad = valid_plan()
    bad["rows"][0]["exercise_id"] = "EX99"
    llm = ScriptedLLM([bad, bad, bad])
    result = PlanService(lambda: llm).submit(envelope())
    assert result["status"] == "accepted" and result["generation_status"] == "failed"
    assert result["result"]["validation"]["passed"] is False
    assert len(llm.calls) == 3 and result["result"]["revisions_used"] == 2


def test_key_error_reaches_web(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("module2.llm.ENV_FILE", tmp_path / "absent.env")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([sample()]), encoding="utf-8")
    with Running(create_planner(port=0)) as planner:
        with Running(create_web(tmp_path / "web.sqlite3", seed, planner.base, port=0)) as web:
            code, body = http(web.base, "/api/v1/soldiers/22-00000001/module2", {})
            assert code == 502 and body["error"]["code"] == "module2_api_key_missing"
            assert "Claude API 키" in body["error"]["message"]


def test_llm_request_and_response_without_paid_call():
    calls = []
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(valid_plan()))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=2),
                               model="test-model", stop_reason="end_turn")
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get_final_message(self): return response
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream()
    client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    out = ClaudePlanLLM(model="test-model", client=client).complete("system", [{"role": "user", "content": "test"}])
    assert out.plan == valid_plan()
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_nonfinite_input_is_rejected():
    raw = planner_payload(envelope())
    raw["difference_matrix"][0][0] = float("nan")
    with pytest.raises(ContractError):
        validate_contract(raw, load_catalog())


def test_malformed_plan_is_reported_after_revision_limit():
    malformed = {"summary": "bad shape", "rows": [{"exercise_id": ["EX01"], "week": 1}]}
    llm = ScriptedLLM([malformed, malformed, malformed])
    response = PlanService(lambda: llm).submit(envelope())
    assert response["generation_status"] == "failed"
    assert response["plan"] == []
    assert response["result"]["validation"]["checks"]["structure"] == "fail"


def test_normalized_plan_rows_match_validation():
    plan = valid_plan()
    for row in plan["rows"]:
        row["week"] = str(row["week"])
    response = PlanService(lambda: ScriptedLLM([plan])).submit(envelope())
    assert response["generation_status"] == "passed"
    assert {row["week"] for row in response["plan"]} == set(range(1, 9))
