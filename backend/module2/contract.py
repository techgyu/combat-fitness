"""모듈 1 입력이 API 계약(docs/module2/PROJECT_SPEC_v3.md 1.6)에 맞는지 검증.

실패하면 입력 오류를 반환하고 Claude를 호출하지 않음.
"""
from __future__ import annotations

from typing import Any
import json
from pathlib import Path

from pydantic import ValidationError

from .catalog import Catalog
from .models import ModuleOnePayload, Need, PlanInput

_EPS = 1e-6


class ContractError(ValueError):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def validate_contract(raw: dict[str, Any], catalog: Catalog) -> PlanInput:
    try:
        payload = ModuleOnePayload.model_validate(raw)
    except ValidationError as e:
        raise ContractError(
            [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        ) from None

    spec = catalog.rules["contract"]
    issues: list[str] = []

    if payload.schema_version != spec["schema_version"]:
        issues.append(f"schema_version: expected {spec['schema_version']}, got {payload.schema_version}")
    if payload.operation != spec["operation"]:
        issues.append(f"operation: expected {spec['operation']}, got {payload.operation}")
    if payload.column_order != spec["column_order"]:
        issues.append(f"column_order: expected {spec['column_order']}, got {payload.column_order}")
    if payload.column_units != spec["column_units"]:
        issues.append(f"column_units: expected {spec['column_units']}, got {payload.column_units}")
    if payload.improvement_columns != spec["improvement_columns"]:
        issues.append(f"improvement_columns: expected {spec['improvement_columns']}, got {payload.improvement_columns}")

    m = payload.difference_matrix
    if len(m) != 1 or len(m[0]) != 4:
        issues.append(f"difference_matrix: expected shape 1x4, got {len(m)}x{len(m[0]) if m else 0}")
        raise ContractError(issues)
    push, sit, run, ratio = m[0]

    # Keep signed goal-current values, including performance above grade 1.
    if abs(ratio) > _EPS:
        issues.append(f"difference_matrix.load_to_body_weight_ratio: must be 0, got {ratio}")

    # 차이값은 goal - current와 같아야 함.
    cur, goal = payload.current_records, payload.goal_records
    criteria = json.loads((Path(__file__).resolve().parents[1] / "module1/config/target_criteria.json").read_text(encoding="utf-8"))
    reference = next(t for t in criteria["thresholds"] if t["age_min"] <= payload.soldier.age <= t["age_max"])
    for col in spec["improvement_columns"]:
        if getattr(goal, col) != reference[col]:
            issues.append(f"goal_records.{col}: must equal the age-specific grade-1 reference ({reference[col]})")
    if payload.soldier.sex not in ("M", "male") or payload.soldier.role != "infantry_rifleman":
        issues.append("soldier: supported profile is male infantry_rifleman")
    for col, d in (("pushups_2min", push), ("situps_2min", sit), ("run_3km_seconds", run)):
        expected = getattr(goal, col) - getattr(cur, col)
        if abs(expected - d) > _EPS:
            issues.append(f"difference_matrix.{col}: {d} != goal - current ({expected})")

    # 하중 정보.
    lc = payload.load_context
    if abs(lc.combat_load_kg - spec["combat_load_kg"]) > _EPS:
        issues.append(f"load_context.combat_load_kg: expected {spec['combat_load_kg']}, got {lc.combat_load_kg}")
    if lc.usage != "reference_only":
        issues.append(f"load_context.usage: expected reference_only, got {lc.usage}")
    expected_ratio = lc.combat_load_kg / payload.soldier.weight_kg
    if abs(lc.load_to_body_weight_ratio - expected_ratio) > spec["load_ratio_tolerance"]:
        issues.append(
            f"load_context.load_to_body_weight_ratio: {lc.load_to_body_weight_ratio} != "
            f"combat_load_kg / weight_kg ({expected_ratio:.3f})"
        )

    if not payload.soldier.synthetic:
        issues.append("soldier.synthetic: only synthetic data is allowed")

    # 버전은 모듈 2가 쓰는 데이터 팩 버전과 같아야 함.
    if payload.versions:
        for key in ("exercise_catalog", "plan_rules"):
            sent = getattr(payload.versions, key)
            if sent is not None and sent != catalog.versions[key]:
                issues.append(f"versions.{key}: module 1 uses {sent}, module 2 has {catalog.versions[key]}")

    if issues:
        raise ContractError(issues)

    units = dict(zip(spec["column_order"], spec["column_units"]))
    needs = []
    for col, d in (("pushups_2min", push), ("situps_2min", sit), ("run_3km_seconds", run)):
        needs_improvement = d < -_EPS if col == "run_3km_seconds" else d > _EPS
        if abs(d) <= _EPS:
            direction = "met"
        elif needs_improvement:
            direction = "increase" if d > 0 else "decrease"
        else:
            direction = "maintain"
        needs.append(Need(column=col, delta=d, unit=units[col], direction=direction,
                          amount=abs(d) if needs_improvement else 0))
    return PlanInput(payload=payload, needs=needs)
