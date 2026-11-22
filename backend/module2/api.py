"""Optional FastAPI entry point, sharing the desktop application's service."""
from functools import lru_cache
from typing import Any
from fastapi import Body, Depends, FastAPI
from fastapi.responses import JSONResponse
from .catalog import load_catalog
from .llm import ClaudePlanLLM
from .service import PlanService, ServiceError

app = FastAPI(title="Combat fitness module 2", version="2.0.0")

@lru_cache
def get_catalog():
    return load_catalog()

def get_llm():
    return ClaudePlanLLM()

@app.get("/health")
def health(catalog=Depends(get_catalog)):
    return PlanService(catalog=catalog).health()

def respond(payload, catalog, llm, envelope):
    service = PlanService(catalog=catalog)
    try:
        result = service.submit(payload, llm) if envelope else service.generate(payload, llm)
        return JSONResponse(content=result)
    except ServiceError as exc:
        return JSONResponse(status_code=exc.http_status, content=exc.body())

@app.post("/api/v1/plans")
def submit(payload: dict[str, Any] = Body(...), catalog=Depends(get_catalog), llm=Depends(get_llm)):
    return respond(payload, catalog, llm, True)

@app.post("/plan")
def create_plan(payload: dict[str, Any] = Body(...), catalog=Depends(get_catalog), llm=Depends(get_llm)):
    return respond(payload, catalog, llm, False)
