"""공용 테스트 데이터: 명세 예시 입력(PROJECT_SPEC 1.5)과 모든 검증을 통과하는 계획."""
from __future__ import annotations

import copy
from typing import Any

SPEC_PAYLOAD: dict[str, Any] = {
    "schema_version": "2.0",
    "operation": "goal_minus_now",
    "column_order": ["pushups_2min", "situps_2min", "run_3km_seconds", "load_to_body_weight_ratio"],
    "column_units": ["reps", "reps", "seconds", "ratio"],
    "difference_matrix": [[16, 18, -148, 0]],
    "improvement_columns": ["pushups_2min", "situps_2min", "run_3km_seconds"],
    "load_context": {"combat_load_kg": 15, "load_to_body_weight_ratio": 0.2, "usage": "reference_only"},
    "soldier": {"soldier_id": "22-00000001", "height_cm": 175, "weight_kg": 75, "bmi": 24.5, "age": 23,
                "sex": "M", "role": "infantry_rifleman", "synthetic": True},
    "current_records": {"pushups_2min": 48, "situps_2min": 60, "run_3km_seconds": 960},
    "goal_records": {"pushups_2min": 64, "situps_2min": 78, "run_3km_seconds": 812},
    "versions": {"standards": "1.0", "exercise_catalog": "1.0", "plan_rules": "1.0"},
}


def payload(**overrides: Any) -> dict[str, Any]:
    p = copy.deepcopy(SPEC_PAYLOAD)
    p.update(overrides)
    return p


def valid_plan() -> dict[str, Any]:
    """8-week plan for SPEC_PAYLOAD that satisfies every rule in plan_rules_v1.0."""
    phases = ["처음 시작하는", "자세에 익숙해지는", "양을 조금 늘리는", "꾸준히 쌓는",
              "중반을 넘기는", "강도를 높이는", "가장 많이 하는", "마무리하는"]
    rows = []
    for w in range(1, 9):
        push_reps, sit_reps = 15 + w, 20 + w
        run_min = 20 + min(w, 7)  # 8주차는 7주차보다 늘리지 않음
        ph = phases[w - 1]
        rows += [
            {"week": w, "exercise_id": "EX29", "sessions_per_week": 3, "sets": None, "reps": None,
             "seconds": None, "minutes": 10, "load_kg": None, "targets": ["recovery"],
             "reason": f"{ph} 주라 운동 전 준비운동을 10분 합니다.", "evidence_ids": ["EV02"]},
            {"week": w, "exercise_id": "EX20", "sessions_per_week": 3, "sets": 3, "reps": push_reps,
             "seconds": None, "minutes": None, "load_kg": None, "targets": ["pushups_2min"],
             "reason": f"팔굽혀펴기 16회 증가를 위해 {ph} 주에는 3세트 {push_reps}회를 합니다.",
             "evidence_ids": ["EV01", "EV02"]},
            {"week": w, "exercise_id": "EX14", "sessions_per_week": 3, "sets": 3, "reps": sit_reps,
             "seconds": None, "minutes": None, "load_kg": None, "targets": ["situps_2min"],
             "reason": f"윗몸일으키기 18회 증가를 위해 {ph} 주에는 3세트 {sit_reps}회를 합니다.",
             "evidence_ids": ["EV01"]},
            {"week": w, "exercise_id": "EX01", "sessions_per_week": 2, "sets": None, "reps": None,
             "seconds": None, "minutes": run_min, "load_kg": None,
             "targets": ["run_3km_seconds", "load_carriage"],
             "reason": f"3km 148초 단축을 위해 {ph} 주에는 {run_min}분 지속주를 합니다.",
             "evidence_ids": ["EV02", "EV05"]},
        ]
        if w <= 4:
            rows.append({"week": w, "exercise_id": "EX26", "sessions_per_week": 2, "sets": 2, "reps": None,
                         "seconds": 60, "minutes": None, "load_kg": None, "targets": ["load_carriage"],
                         "reason": f"15kg 군장 준비를 위해 {ph} 주에 덤벨을 들고 걷습니다.",
                         "evidence_ids": ["EV04"]})
        else:
            rows.append({"week": w, "exercise_id": "EX07", "sessions_per_week": 2, "sets": 3, "reps": 15,
                         "seconds": None, "minutes": None, "load_kg": None, "targets": ["load_carriage"],
                         "reason": f"15kg 군장 준비를 위해 {ph} 주에 하체 근지구력 운동을 합니다.",
                         "evidence_ids": ["EV04"]})
        if w >= 3:
            rows.append({"week": w, "exercise_id": "EX03", "sessions_per_week": 1, "sets": None, "reps": None,
                         "seconds": None, "minutes": 15, "load_kg": None, "targets": ["run_3km_seconds"],
                         "reason": f"3km 148초 단축을 위해 {ph} 주에 템포런을 합니다.",
                         "evidence_ids": ["EV02"]})
    return {
        "summary": "팔굽혀펴기 16회, 윗몸일으키기 18회 증가와 3km 달리기 148초 단축을 목표로 한 8주 계획입니다. "
                   "전투하중 15kg의 하중비 0.2는 참고 정보입니다.",
        "rows": rows,
    }
