"""Expose the module-2 data pack through the module-1 resource contract.

Only field names are adapted; exercise IDs, evidence and dose limits have one source.
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "module2" / "data"


def load_planning_resources():
    def read(name):
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    exercises = read("exercises_v1.0.json")
    evidence = read("evidence_v1.0.json")
    rules = read("plan_rules_v1.0.json")
    catalog = {
        "catalog_version": exercises["version"],
        "review_status": "prototype_not_clinically_validated",
        "exercise_count": len(exercises["exercises"]),
        "sources": [{**e, "id": e["evidence_id"]} for e in evidence["evidence"]],
        "exercises": [
            {**e, "target_domains": e["related_tests"], "required_equipment": e["equipment"],
             "allowed_dose": {k: {"min": v[0], "max": v[1]} for k, v in e["dose"].items() if k != "type"},
             "frequency_per_week": {"min": e["frequency_per_week"][0], "max": e["frequency_per_week"][1]},
             "dose_basis": "prototype_assumption_not_validated_prescription"}
            for e in exercises["exercises"]
        ],
    }
    planning = {
        "rules_version": rules["version"], "duration_weeks": rules["plan_weeks"]["value"],
        "min_exercises_per_week": rules["exercises_per_week"]["min"],
        "max_exercises_per_week": rules["exercises_per_week"]["max"],
        "load_ratio_usage": "reference_only", "goal_policy": "fixed_grade1_reference",
        "max_revisions_after_initial": rules["max_revisions"]["value"],
        "guarantee_target_achievement": False, "planner_rules": rules,
    }
    return {"exercise_catalog": catalog, "planning_rules": planning}
