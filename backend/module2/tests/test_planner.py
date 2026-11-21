"""미리 정한 답을 돌려주는 가짜 LLM으로 planner 루프를 테스트 (API 호출 없음)."""
import json

from module2.catalog import load_catalog
from module2.llm import LLMResult
from module2.planner import run_planner

from .fixtures import payload, valid_plan

CATALOG = load_catalog()


class ScriptedLLM:
    """미리 정한 출력을 순서대로 돌려주고, 받은 요청을 모두 기록함."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        out = self.outputs.pop(0)
        if isinstance(out, LLMResult):
            return out
        return LLMResult(plan=out, assistant_content=[{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                         model="fake")


def _bad_plan(ex_id="EX99"):
    plan = valid_plan()
    plan["rows"][1]["exercise_id"] = ex_id  # 1주차, 원래 EX20
    return plan


def test_passes_on_first_attempt():
    llm = ScriptedLLM([valid_plan()])
    out = run_planner(payload(), llm, CATALOG)
    assert out["status"] == "passed"
    assert out["revisions_used"] == 0 and len(llm.calls) == 1
    assert len(out["plan"]) == len(valid_plan()["rows"]) and out["plan"][0]["exercise_name"]
    assert out["versions"]["exercise_catalog"] == "1.0" and out["versions"]["standards"] == "1.0"


def test_violation_is_fed_back_and_revision_passes():
    llm = ScriptedLLM([_bad_plan(), valid_plan()])
    out = run_planner(payload(), llm, CATALOG)
    assert out["status"] == "passed" and out["revisions_used"] == 1
    assert [h["passed"] for h in out["history"]] == [False, True]
    # 두 번째 호출에는 첫 계획과 위반 내역이 함께 들어 있어야 함
    msgs = llm.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "EX99" in msgs[2]["content"] and "catalog" in msgs[2]["content"]


def test_fails_after_revision_limit():
    llm = ScriptedLLM([_bad_plan(), _bad_plan(), _bad_plan()])
    out = run_planner(payload(), llm, CATALOG)
    assert out["status"] == "failed" and out["stop_reason"] == "revision_limit_exceeded"
    assert len(llm.calls) == 3  # 최초 1회 + 수정 2회, 그 이상은 없음
    assert out["revisions_used"] == 2
    assert out["validation"]["violations"]


def test_unparseable_output_counts_as_attempt():
    broken = LLMResult(plan=None, assistant_content=[{"type": "text", "text": "{"}], error="invalid_json")
    llm = ScriptedLLM([broken, valid_plan()])
    out = run_planner(payload(), llm, CATALOG)
    assert out["status"] == "passed" and out["history"][0]["error"] == "invalid_json"


def test_refusal_stops_the_loop():
    refused = LLMResult(plan=None, assistant_content=[], error="refusal")
    llm = ScriptedLLM([refused])
    out = run_planner(payload(), llm, CATALOG)
    assert out["status"] == "failed" and out["stop_reason"] == "model_refusal"
    assert len(llm.calls) == 1


def test_input_error_skips_the_model():
    llm = ScriptedLLM([])
    out = run_planner(payload(difference_matrix=[[16, 18, 148, 0]]), llm, CATALOG)
    assert out["status"] == "input_error" and out["errors"]
    assert llm.calls == []


def test_system_prompt_is_rendered_from_data_pack():
    llm = ScriptedLLM([valid_plan()])
    run_planner(payload(), llm, CATALOG)
    system = llm.calls[0]["system"]
    assert "EX30" in system and str(CATALOG.rules["weekly_caps"]["max_total_sets"]) in system
    assert '"exercise_id": "EX27"' not in system  # 제외된 운동은 후보 목록에서 빠짐
    assert '"rep_caps"' in llm.calls[0]["messages"][0]["content"]
