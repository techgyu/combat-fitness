"""모듈 2 데이터 팩(운동 목록, 근거표, 계획 규칙)을 읽어 들임.

검증기가 쓰는 기준값은 모두 이 파일들에서 오며, 코드에 하드코딩하지 않음.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_VERSION = "1.0"


class CatalogError(ValueError):
    """데이터 팩 내부 값이 서로 맞지 않음."""


@dataclass(frozen=True)
class Catalog:
    exercises: dict[str, dict[str, Any]]
    evidence: dict[str, dict[str, Any]]
    rules: dict[str, Any]
    versions: dict[str, str]
    related_tests_vocabulary: tuple[str, ...]

    def exercise(self, exercise_id: str) -> dict[str, Any] | None:
        return self.exercises.get(exercise_id)


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_catalog(version: str = DEFAULT_VERSION, data_dir: Path = DATA_DIR) -> Catalog:
    ex_doc = _read(data_dir / f"exercises_v{version}.json")
    ev_doc = _read(data_dir / f"evidence_v{version}.json")
    rules = _read(data_dir / f"plan_rules_v{version}.json")

    exercises = {e["exercise_id"]: e for e in ex_doc["exercises"]}
    evidence = {e["evidence_id"]: e for e in ev_doc["evidence"]}
    catalog = Catalog(
        exercises=exercises,
        evidence=evidence,
        rules=rules,
        versions={
            "exercise_catalog": ex_doc["version"],
            "evidence": ev_doc["version"],
            "plan_rules": rules["version"],
        },
        related_tests_vocabulary=tuple(ex_doc["related_tests_vocabulary"]),
    )
    check_catalog(catalog)
    return catalog


def check_catalog(catalog: Catalog) -> None:
    """데이터 팩에 없는 ID나 허용되지 않은 장비가 있으면 즉시 실패."""
    problems: list[str] = []
    allowed_equipment = set(catalog.rules["allowed_equipment"]["value"])
    vocab = set(catalog.related_tests_vocabulary)
    if len(catalog.exercises) != 30:
        problems.append(f"expected 30 exercises, found {len(catalog.exercises)}")
    for ex_id, ex in catalog.exercises.items():
        for ev in ex["evidence_ids"]:
            if ev not in catalog.evidence:
                problems.append(f"{ex_id}: unknown evidence_id {ev}")
        for eq in ex["equipment"]:
            if eq not in allowed_equipment:
                problems.append(f"{ex_id}: equipment {eq} not in allowed_equipment")
        for t in ex["related_tests"]:
            if t not in vocab:
                problems.append(f"{ex_id}: related_test {t} not in vocabulary")
        dose = ex["dose"]
        for key, rng in dose.items():
            if key == "type":
                continue
            if not (isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1]):
                problems.append(f"{ex_id}: dose.{key} must be [min, max]")
    for ex_id in catalog.rules["excluded_exercises"]["value"] + catalog.rules["run_quality"]["exercise_ids"]:
        if ex_id not in catalog.exercises:
            problems.append(f"excluded_exercises: unknown {ex_id}")
    for ex_id, record in catalog.rules["rep_cap_by_record"]["exercise_to_record"].items():
        if catalog.exercises.get(ex_id, {}).get("dose", {}).get("type") != "reps":
            problems.append(f"rep_cap_by_record: {ex_id} must be a registered reps exercise")
        if record not in catalog.rules["contract"]["improvement_columns"]:
            problems.append(f"rep_cap_by_record: unknown record {record}")
    if problems:
        raise CatalogError("; ".join(problems))
