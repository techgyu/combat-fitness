import httpx
import anthropic
from fastapi.testclient import TestClient

from module2.api import app, get_llm

from .fixtures import payload, valid_plan
from .test_planner import ScriptedLLM


def _client(llm):
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_health_reports_versions():
    r = _client(ScriptedLLM([])).get("/health")
    assert r.status_code == 200 and r.json()["versions"]["plan_rules"] == "1.0"


def test_plan_endpoint_returns_passed_plan():
    r = _client(ScriptedLLM([valid_plan()])).post("/plan", json=payload())
    body = r.json()
    assert r.status_code == 200 and body["status"] == "passed"
    assert body["records"][2]["column"] == "run_3km_seconds" and body["records"][2]["amount"] == 148


def test_plan_endpoint_rejects_contract_violation():
    r = _client(ScriptedLLM([])).post("/plan", json=payload(column_units=["reps", "reps", "min", "ratio"]))
    assert r.status_code == 422 and r.json()["status"] == "input_error"


class FailingLLM:
    def complete(self, system, messages):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None)


def test_auth_error_is_reported_without_crashing():
    r = _client(FailingLLM()).post("/plan", json=payload())
    assert r.status_code == 502 and r.json()["status"] == "llm_auth_error"
