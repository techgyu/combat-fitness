"""생성 → 검증 → 수정 루프 (docs/module2/PROJECT_SPEC_v3.md 2.2-2.6).

수정 횟수와 통과 판정은 모델이 아닌 코드가 결정함.
"""
from __future__ import annotations

from typing import Any

from .catalog import Catalog
from .contract import ContractError, validate_contract
from .llm import PlanLLM
from .models import PlanInput, PlanRow, ValidationReport, Violation
from pydantic import ValidationError
from .prompts import build_initial_message, build_revision_message, build_system_prompt
from .validator import build_report, validate_plan

SYNTHETIC_NOTICE = "합성 데이터로 생성한 결과입니다. 실제 장병 정보가 아닙니다."
DISCLAIMER = "검증 통과는 등록된 규칙을 지켰다는 뜻이며, 실제 훈련 효과나 임무 수행능력을 입증하지 않습니다."


def _versions(catalog: Catalog, plan_input: PlanInput | None) -> dict[str, Any]:
    v: dict[str, Any] = dict(catalog.versions)
    if plan_input and plan_input.payload.versions:
        v["standards"] = plan_input.payload.versions.standards
    return v


def _invalid_output_report(error: str) -> ValidationReport:
    v = Violation(check="structure", field="output", actual=error,
                  reason="model output could not be parsed as a plan; return the full plan as JSON")
    return build_report([v])


def _enrich_rows(plan: dict[str, Any] | None, catalog: Catalog) -> list[dict[str, Any]]:
    if not isinstance(plan, dict) or not isinstance(plan.get("rows"), list):
        return []
    rows = []
    normalized = []
    for raw in plan["rows"]:
        try:
            normalized.append(PlanRow.model_validate(raw).model_dump())
        except ValidationError:
            continue  # The corresponding schema violation remains in the report/history.
    for r in sorted(normalized, key=lambda row: (row["week"], row["exercise_id"])):
        ex = catalog.exercise(r["exercise_id"])
        rows.append({**r, "exercise_name": ex["name"] if ex else None,
                     "category": ex["category"] if ex else None})
    return rows


def _overview(plan_input: PlanInput) -> dict[str, Any]:
    p = plan_input.payload
    return {
        "soldier": p.soldier.model_dump(),
        "records": [
            {"column": n.column, "unit": n.unit,
             "current": getattr(p.current_records, n.column),
             "goal": getattr(p.goal_records, n.column),
             "delta": n.delta, "direction": n.direction, "amount": n.amount}
            for n in plan_input.needs
        ],
        "load_context": p.load_context.model_dump(),
    }


def run_planner(raw_payload: dict[str, Any], llm: PlanLLM, catalog: Catalog) -> dict[str, Any]:
    try:
        plan_input = validate_contract(raw_payload, catalog)
    except ContractError as e:
        return {"status": "input_error", "errors": e.issues, "versions": _versions(catalog, None),
                "notice": SYNTHETIC_NOTICE}

    max_revisions = catalog.rules["max_revisions"]["value"]
    system = build_system_prompt(catalog)
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_initial_message(plan_input, catalog)}]
    history: list[dict[str, Any]] = []
    plan: dict[str, Any] | None = None
    report: ValidationReport | None = None
    status = "failed"
    stop_reason = "revision_limit_exceeded"

    for attempt in range(max_revisions + 1):
        result = llm.complete(system, messages)
        messages.append({"role": "assistant", "content": result.assistant_content})

        if result.error == "refusal":
            history.append({"attempt": attempt, "kind": "initial" if attempt == 0 else "revision",
                            "passed": False, "error": "refusal", "violations": []})
            stop_reason = "model_refusal"
            break

        if result.plan is None:
            report = _invalid_output_report(result.error or "no_plan")
        else:
            plan = result.plan
            report = validate_plan(plan, plan_input, catalog)

        history.append({
            "attempt": attempt,
            "kind": "initial" if attempt == 0 else "revision",
            "passed": report.passed,
            "error": result.error,
            "violation_count": len(report.violations),
            "violations": [v.model_dump(exclude_none=True) for v in report.violations],
            "model": result.model,
            "usage": result.usage,
        })

        if report.passed:
            status, stop_reason = "passed", None
            break
        if attempt < max_revisions:
            messages.append({"role": "user",
                             "content": build_revision_message(report.violations, attempt + 1, max_revisions)})

    return {
        "status": status,
        "stop_reason": stop_reason,
        **_overview(plan_input),
        "summary": plan.get("summary") if isinstance(plan, dict) and isinstance(plan.get("summary"), str) else None,
        "plan": _enrich_rows(plan, catalog),
        "validation": report.model_dump() if report else None,
        "revisions_used": max(0, len(history) - 1),
        "max_revisions": max_revisions,
        "history": history,
        "versions": _versions(catalog, plan_input),
        "notice": SYNTHETIC_NOTICE,
        "disclaimer": DISCLAIMER,
    }
