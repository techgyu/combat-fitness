"""모듈 2 공용 데이터 타입: 모듈 1 입력, 계획, 위반 내역."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------- 모듈 1 → 모듈 2 입력 (docs/PROJECT_SPEC.md 1.6) ----------


class LoadContext(BaseModel):
    combat_load_kg: float
    load_to_body_weight_ratio: float
    usage: str


class Soldier(BaseModel):
    soldier_id: str
    height_cm: float = Field(gt=0)
    weight_kg: float = Field(gt=0)
    bmi: Optional[float] = None
    age: int = Field(gt=0)
    sex: str
    role: str
    synthetic: bool = True


class Records(BaseModel):
    pushups_2min: float = Field(ge=0)
    situps_2min: float = Field(ge=0)
    run_3km_seconds: float = Field(gt=0)


class Versions(BaseModel):
    standards: Optional[str] = None
    exercise_catalog: Optional[str] = None
    plan_rules: Optional[str] = None


class ModuleOnePayload(BaseModel):
    schema_version: str
    operation: str
    column_order: list[str]
    column_units: list[str]
    difference_matrix: list[list[float]]
    improvement_columns: list[str]
    load_context: LoadContext
    soldier: Soldier
    current_records: Records
    goal_records: Records
    versions: Optional[Versions] = None


class Need(BaseModel):
    """차이 행렬에서 구한 종목별 개선 필요량."""

    column: str
    delta: float
    unit: str
    direction: str  # "increase" | "decrease" | "met"
    amount: float  # abs(delta)


class PlanInput(BaseModel):
    """검증된 입력과 개선 필요량. planner가 이 값으로 작업함."""

    payload: ModuleOnePayload
    needs: list[Need]

    @property
    def nonzero_columns(self) -> list[str]:
        return [n.column for n in self.needs if n.direction != "met"]


# ---------- Claude가 작성한 계획 ----------


class PlanRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week: int
    exercise_id: str
    sessions_per_week: int
    sets: Optional[int] = None
    reps: Optional[int] = None
    seconds: Optional[int] = None
    minutes: Optional[int] = None
    load_kg: Optional[float] = None
    targets: list[str]
    reason: str
    evidence_ids: list[str]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    rows: list[PlanRow]


# ---------- 검증 결과 ----------

CHECKS = (
    "structure",      # 계획 구조
    "catalog",        # 운동 목록
    "volume",         # 운동량·빈도
    "conditions",     # 적용 조건
    "evidence",       # 추천 근거
    "explanation",    # 설명 수치
    "load_usage",     # 하중 정보 활용
)


class Violation(BaseModel):
    check: str
    reason: str
    week: Optional[int] = None
    exercise_id: Optional[str] = None
    field: Optional[str] = None
    allowed: Any = None
    actual: Any = None


class ValidationReport(BaseModel):
    passed: bool
    violations: list[Violation]
    checks: dict[str, str]  # check -> "pass" | "fail"
