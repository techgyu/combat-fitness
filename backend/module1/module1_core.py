"""Raw records -> grade-1 goals -> signed differences. No scoring."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTRACT_VERSION = "2.0.0"
COLUMNS = ["pushups_2min", "situps_2min", "run_3km_seconds", "load_to_body_weight_ratio"]
UNITS = ["repetitions/120s", "repetitions/120s", "s", "dimensionless"]


def load_stage(filename):
    spec = importlib.util.spec_from_file_location(filename[:-3], ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_stage("03_validate_and_compute.py")


class DomainError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details or []


def decode_json(data):
    return json.loads(data, parse_constant=validator.reject_constant,
                      object_pairs_hook=validator.unique_object)


def validate_resources(resources):
    try:
        criteria, catalog, rules = (resources[k] for k in ("target_criteria", "exercise_catalog", "planning_rules"))
        if not (criteria["target_version"] and catalog["catalog_version"] and rules["rules_version"]):
            raise ValueError("Resource or contract invariant failed.")
        protocol = criteria["measurement_protocol"]
        for key, value in (("pushups_duration_seconds", 120), ("situps_duration_seconds", 120),
                           ("run_distance_m", 3000), ("baseline_test_load_kg", 0)):
            if not (protocol[key] == value and not isinstance(protocol[key], bool)):
                raise ValueError("Resource or contract invariant failed.")
        if not (criteria["load_context"]["usage"] == "reference_only"):
            raise ValueError("Resource or contract invariant failed.")
        if not (criteria["load_context"]["combat_load_kg"] == 15):
            raise ValueError("Resource or contract invariant failed.")
        if not (criteria["goal_policy"]["difference_operation"] == "goal_minus_now"):
            raise ValueError("Resource or contract invariant failed.")
        policy = criteria["goal_policy"]
        if (policy.get("mode") != "fixed_grade1_reference"
                or any(policy.get(key) != "reference" for key in ("pushups", "situps", "run_3km_seconds"))
                or policy.get("difference_clipping") != "none"):
            raise ValueError("Goal must use the fixed grade-1 reference without clipping differences.")
        for age in range(18, 30):
            matches = [t for t in criteria["thresholds"] if t["age_min"] <= age <= t["age_max"]]
            if not (len(matches) == 1):
                raise ValueError("Resource or contract invariant failed.")
            for key in COLUMNS[:3]:
                value = matches[0][key]
                if not (type(value) is int and value > 0):
                    raise ValueError("Resource or contract invariant failed.")
        if not (criteria["source"]["url"].startswith("https://")):
            raise ValueError("Resource or contract invariant failed.")
        exercises = catalog["exercises"]
        if not (len(exercises) == catalog["exercise_count"] == 30):
            raise ValueError("Resource or contract invariant failed.")
        if not (len({e["exercise_id"] for e in exercises}) == 30):
            raise ValueError("Resource or contract invariant failed.")
        sources = {s["id"] for s in catalog["sources"]}
        if not (len(sources) == len(catalog["sources"])):
            raise ValueError("Resource or contract invariant failed.")
        for exercise in exercises:
            for key in ("exercise_id", "name", "target_domains", "difficulty",
                        "allowed_dose", "restrictions", "evidence_ids", "dose_basis"):
                if not (exercise[key]):
                    raise ValueError("Resource or contract invariant failed.")
            if not (isinstance(exercise["required_equipment"], list)):
                raise ValueError("Resource or contract invariant failed.")
            if not (set(exercise["evidence_ids"]) <= sources):
                raise ValueError("Resource or contract invariant failed.")
            for limits in [exercise["frequency_per_week"], *exercise["allowed_dose"].values()]:
                if not (all(type(limits[k]) in (int, float) and math.isfinite(limits[k])
                           for k in ("min", "max"))):
                    raise ValueError("Resource or contract invariant failed.")
                if not (0 <= limits["min"] <= limits["max"]):
                    raise ValueError("Resource or contract invariant failed.")
        if not (rules["duration_weeks"] == 8 and rules["load_ratio_usage"] == "reference_only"):
            raise ValueError("Resource or contract invariant failed.")
        if not (2 <= rules["min_exercises_per_week"] <= rules["max_exercises_per_week"]):
            raise ValueError("Resource or contract invariant failed.")
    except (KeyError, TypeError, AssertionError, ValueError) as exc:
        raise DomainError("invalid_resources", "목표표·운동표·계획 규칙의 형식 또는 범위를 확인하세요.") from exc


class Module1:
    def __init__(self, config_dir=None):
        directory = Path(config_dir or ROOT / "config")
        self.resources = {name: decode_json((directory / (name + ".json")).read_text(encoding="utf-8"))
                          for name in ("target_criteria", "exercise_catalog", "planning_rules")}
        validate_resources(self.resources)
        self.versions = {
            "target": self.resources["target_criteria"]["target_version"],
            "catalog": self.resources["exercise_catalog"]["catalog_version"],
            "rules": self.resources["planning_rules"]["rules_version"],
            "measurement_protocol": self.resources["target_criteria"]["measurement_protocol"]["version"],
            "validator": validator.VERSION,
        }
        self.resource_sha256 = hashlib.sha256(json.dumps(
            self.resources, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")).hexdigest()

    def evaluate(self, raw):
        report = validator.validate_and_compute([raw])
        if report["status"] != "passed":
            raise DomainError("validation_failed", "입력값을 확인하세요.", report["errors"])
        return self.from_validated(report["records"][0]), report

    def from_validated(self, row):
        criteria = self.resources["target_criteria"]
        reference = next(t for t in criteria["thresholds"] if t["age_min"] <= row["age"] <= t["age_max"])
        now = [row[k] for k in COLUMNS[:3]] + [row["load_ratio"]]
        goal = [reference[key] for key in COLUMNS[:3]] + [now[3]]
        difference = [round(g - n, 6) for n, g in zip(now, goal)]
        return {
            "contract_version": CONTRACT_VERSION,
            "soldier_id": row["soldier_id"],
            "profile": {k: row[k] for k in (
                "age", "age_basis", "sex", "role", "height_cm", "weight_kg", "bmi", "is_synthetic")},
            "measurement_protocol": copy.deepcopy(criteria["measurement_protocol"]),
            "column_order": COLUMNS[:], "column_units": UNITS[:],
            "difference_operation": "goal_minus_now",
            "now_matrix": [now], "goal_matrix": [goal], "difference_matrix": [difference],
            "current_records": {k: now[i] for i, k in enumerate(COLUMNS[:3])},
            "goal_records": {k: goal[i] for i, k in enumerate(COLUMNS[:3])},
            "reference_records": {k: reference[k] for k in COLUMNS[:3]},
            "load_context": {**copy.deepcopy(criteria["load_context"]),
                             "load_to_body_weight_ratio": row["load_ratio"],
                             "load_ratio_percent": row["load_ratio_percent"]},
            "training_context": {"available_equipment": None, "restrictions": None,
                                 "status": "not_collected"},
            "planning_request": copy.deepcopy(criteria["planning"]),
            "versions": self.versions.copy(),
            "resources_sha256": self.resource_sha256,
        }

    def envelope(self, payload, request_id):
        return {"contract_version": CONTRACT_VERSION, "request_id": request_id,
                "module1_result": payload, "shared_resources": copy.deepcopy(self.resources)}


def verify_envelope(body):
    """Receiver-side semantic checks, also used by the mock and contract tests."""
    try:
        if not (isinstance(body, dict) and body["contract_version"] == CONTRACT_VERSION):
            raise ValueError("Resource or contract invariant failed.")
        if not (isinstance(body["request_id"], str) and 1 <= len(body["request_id"]) <= 100):
            raise ValueError("Resource or contract invariant failed.")
        p = body["module1_result"]
        resources = body["shared_resources"]
        validate_resources(resources)
        if not (p["contract_version"] == CONTRACT_VERSION and p["column_order"] == COLUMNS):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["column_units"] == UNITS and p["difference_operation"] == "goal_minus_now"):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["versions"]["target"] == resources["target_criteria"]["target_version"]):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["versions"]["catalog"] == resources["exercise_catalog"]["catalog_version"]):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["versions"]["rules"] == resources["planning_rules"]["rules_version"]):
            raise ValueError("Resource or contract invariant failed.")
        digest = hashlib.sha256(json.dumps(resources, sort_keys=True, ensure_ascii=False,
                                           allow_nan=False).encode("utf-8")).hexdigest()
        if not (p["resources_sha256"] == digest):
            raise ValueError("Resource or contract invariant failed.")
        matrices = [p[k] for k in ("now_matrix", "goal_matrix", "difference_matrix")]
        for matrix in matrices:
            if not (isinstance(matrix, list) and len(matrix) == 1 and len(matrix[0]) == 4):
                raise ValueError("Resource or contract invariant failed.")
            if not (all(type(x) in (int, float) and math.isfinite(x) for x in matrix[0])):
                raise ValueError("Resource or contract invariant failed.")
        now, goal, delta = [m[0] for m in matrices]
        if not (delta == [round(g - n, 6) for n, g in zip(now, goal)]):
            raise ValueError("Resource or contract invariant failed.")
        # Repetition differences can be negative; running differences can be
        # positive when the current performance already exceeds the reference.
        if not (delta[3] == 0):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["load_context"]["usage"] == "reference_only"):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["load_context"]["readiness_assessed"] is False):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["load_context"]["combat_load_kg"] == 15):
            raise ValueError("Resource or contract invariant failed.")
        if not (now[3] == goal[3] == p["load_context"]["load_to_body_weight_ratio"]):
            raise ValueError("Resource or contract invariant failed.")
        raw = {**p["profile"], **p["current_records"], "soldier_id": p["soldier_id"],
               "combat_load_kg": 15, **{k: p["measurement_protocol"][k] for k in (
                   "pushups_duration_seconds", "situps_duration_seconds", "run_distance_m", "baseline_test_load_kg")}}
        report = validator.validate_and_compute([raw])
        if not (report["status"] == "passed"):
            raise ValueError("Resource or contract invariant failed.")
        row = report["records"][0]
        if not (now[:3] == [row[k] for k in COLUMNS[:3]] and now[3] == row["load_ratio"]):
            raise ValueError("Resource or contract invariant failed.")
        ref = next(t for t in resources["target_criteria"]["thresholds"]
                   if t["age_min"] <= row["age"] <= t["age_max"])
        expected_goal = [ref[key] for key in COLUMNS[:3]] + [now[3]]
        if not (goal == expected_goal):
            raise ValueError("Resource or contract invariant failed.")
        if not (p["goal_records"] == dict(zip(COLUMNS[:3], goal[:3]))):
            raise ValueError("Resource or contract invariant failed.")
        if p["reference_records"] != p["goal_records"]:
            raise ValueError("Goal records must equal the grade-1 reference records.")
    except (AssertionError, KeyError, TypeError, ValueError, StopIteration, IndexError) as exc:
        raise DomainError("invalid_contract", "모듈 1→2 요청의 형식·버전·계산값이 일치하지 않습니다.") from exc
    return body
