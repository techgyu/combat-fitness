"""Validate the public envelope, then adapt field names for the planner."""
from module1.module1_core import Module1, verify_envelope, DomainError


def planner_payload(envelope, engine=None):
    verify_envelope(envelope)
    engine = engine or Module1()
    if envelope["shared_resources"] != engine.resources:
        raise DomainError("invalid_contract", "두 모듈의 목표표·운동 목록·계획 규칙이 다릅니다. 서버를 다시 시작하세요.")
    p = envelope["module1_result"]
    profile = p["profile"]
    return {
        "schema_version": "2.0", "operation": p["difference_operation"],
        "column_order": p["column_order"], "column_units": ["reps", "reps", "seconds", "ratio"],
        "difference_matrix": p["difference_matrix"], "improvement_columns": p["column_order"][:3],
        "load_context": p["load_context"],
        "soldier": {**profile, "soldier_id": p["soldier_id"], "synthetic": profile["is_synthetic"]},
        "current_records": p["current_records"], "goal_records": p["goal_records"],
        "versions": {"standards": p["versions"]["target"], "exercise_catalog": p["versions"]["catalog"],
                     "plan_rules": p["versions"]["rules"]},
    }
