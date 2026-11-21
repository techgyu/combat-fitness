"""모듈 2 HTTP API.

POST /plan       모듈 1 입력(PROJECT_SPEC 1.6) → 8주 계획 결과
GET  /health     서버 상태 + 데이터 팩 버전

실행: .venv/bin/uvicorn module2.api:app --app-dir backend --reload
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import anthropic
from fastapi import Body, Depends, FastAPI
from fastapi.responses import JSONResponse

from .catalog import Catalog, load_catalog
from .llm import ClaudePlanLLM, PlanLLM
from .planner import run_planner

app = FastAPI(title="combat-load-agent module 2", version="1.0")


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog()


@lru_cache
def get_llm() -> PlanLLM:
    return ClaudePlanLLM()


@app.get("/health")
def health(catalog: Catalog = Depends(get_catalog)) -> dict[str, Any]:
    return {"status": "ok", "versions": catalog.versions}


@app.post("/plan")
def create_plan(
    payload: dict[str, Any] = Body(...),
    catalog: Catalog = Depends(get_catalog),
    llm: PlanLLM = Depends(get_llm),
) -> JSONResponse:
    try:
        result = run_planner(payload, llm, catalog)
    except anthropic.AuthenticationError:
        return _llm_error(502, "llm_auth_error", "Claude API authentication failed; check ANTHROPIC_API_KEY.")
    except anthropic.RateLimitError:
        return _llm_error(503, "llm_rate_limited", "Claude API rate limit reached; retry later.")
    except anthropic.APIStatusError as e:
        return _llm_error(502, "llm_api_error", f"Claude API returned {e.status_code}.")
    except anthropic.APIConnectionError:
        return _llm_error(503, "llm_unreachable", "Could not reach the Claude API.")

    code = 422 if result["status"] == "input_error" else 200
    return JSONResponse(status_code=code, content=result)


def _llm_error(code: int, status: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"status": status, "message": message})
