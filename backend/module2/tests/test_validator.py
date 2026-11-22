import copy

from module2.catalog import load_catalog
from module2.contract import validate_contract
from module2.validator import validate_plan

from .fixtures import payload, valid_plan

CATALOG = load_catalog()
PI = validate_contract(payload(), CATALOG)


def _run(plan, pi=PI):
    return validate_plan(plan, pi, CATALOG)


def _row(plan, week, ex_id):
    return next(r for r in plan["rows"] if r["week"] == week and r["exercise_id"] == ex_id)


def _has(report, check, field=None, week=None):
    return any(v.check == check and (field is None or v.field == field) and (week is None or v.week == week)
               for v in report.violations)


def test_valid_plan_passes_all_checks():
    report = _run(valid_plan())
    assert report.passed, [v.model_dump() for v in report.violations]
    assert set(report.checks.values()) == {"pass"}


# 1. structure
def test_missing_week_is_flagged():
    plan = valid_plan()
    plan["rows"] = [r for r in plan["rows"] if r["week"] != 5]
    r = _run(plan)
    assert _has(r, "structure", "week", 5)


def test_schema_error_is_reported_not_raised():
    plan = valid_plan()
    plan["rows"][0]["intensity"] = "high"
    r = _run(plan)
    assert not r.passed and _has(r, "structure")


def test_duplicate_exercise_in_week_is_flagged():
    plan = valid_plan()
    plan["rows"].append(copy.deepcopy(_row(plan, 1, "EX20")))
    assert _has(_run(plan), "structure", "exercise_id", 1)


# 2. catalog
def test_unknown_exercise_is_flagged():
    plan = valid_plan()
    _row(plan, 6, "EX07")["exercise_id"] = "EX99"
    assert _has(_run(plan), "catalog", "exercise_id", 6)


# 3. volume
def test_reps_out_of_range_is_flagged():
    plan = valid_plan()
    _row(plan, 3, "EX20")["reps"] = 500
    assert _has(_run(plan), "volume", "reps", 3)


def test_sessions_out_of_range_is_flagged():
    plan = valid_plan()
    _row(plan, 3, "EX01")["sessions_per_week"] = 6
    assert _has(_run(plan), "volume", "sessions_per_week", 3)


def test_unused_dose_field_must_be_null():
    plan = valid_plan()
    _row(plan, 1, "EX20")["minutes"] = 10
    assert _has(_run(plan), "volume", "minutes", 1)


def test_too_many_exercises_per_week_is_flagged():
    plan = valid_plan()
    for ex_id, tgt in (("EX13", "load_carriage"), ("EX18", "load_carriage")):
        plan["rows"].append({"week": 1, "exercise_id": ex_id, "sessions_per_week": 2, "sets": 2, "reps": 12,
                             "seconds": None, "minutes": None, "load_kg": None, "targets": [tgt],
                             "reason": "보조 운동입니다.", "evidence_ids": ["EV06"]})
    assert _has(_run(plan), "volume", "exercises_per_week", 1)


def test_fast_weekly_progression_is_flagged():
    plan = valid_plan()
    for ex in ("EX20", "EX14"):
        row = _row(plan, 4, ex)
        row["sessions_per_week"], row["sets"] = 4, 5  # 각 9 → 20세트
    assert _has(_run(plan), "volume", "weekly_total_sets", 4)


# 4. conditions
def test_hard_exercise_in_week_one_is_flagged():
    plan = valid_plan()
    row = _row(plan, 1, "EX26")
    row.update(exercise_id="EX22", sets=3, reps=8, seconds=None, evidence_ids=["EV02"],
               reason="15kg 군장 준비를 위한 상체 근력 운동으로 3세트 8회 실시합니다.")
    assert _has(_run(plan), "conditions", "difficulty", 1)


def test_excluded_rucksack_walking_is_flagged():
    plan = valid_plan()
    plan["rows"].append({"week": 5, "exercise_id": "EX27", "sessions_per_week": 1, "sets": None, "reps": None,
                         "seconds": None, "minutes": 30, "load_kg": 15, "targets": ["load_carriage"],
                         "reason": "배낭 보행 30분입니다.", "evidence_ids": ["EV03"]})
    assert _has(_run(plan), "conditions", "exercise_id", 5)


def test_reps_above_cap_from_current_record_is_flagged():
    plan = valid_plan()
    _row(plan, 6, "EX20")["reps"] = 29  # 48 x 0.6 = 28.8 → 상한 28
    _row(plan, 6, "EX14")["reps"] = 36  # 60 x 0.6 = 36 → 통과
    r = _run(plan)
    caps = [v for v in r.violations if v.field == "reps"]
    assert [(v.exercise_id, v.allowed) for v in caps] == [("EX20", "<= 28")]


def test_final_week_must_not_exceed_previous_week():
    plan = valid_plan()
    _row(plan, 8, "EX01")["minutes"] = 30  # 7주차 27분보다 늘림
    r = _run(plan)
    assert _has(r, "volume", "weekly_total_minutes", 8)


def test_barbell_back_squat_is_excluded():
    plan = valid_plan()
    _row(plan, 6, "EX07").update(exercise_id="EX09", sessions_per_week=1, sets=3, reps=6)
    assert _has(_run(plan), "conditions", "exercise_id", 6)


def test_missing_high_intensity_run_is_flagged():
    plan = valid_plan()
    plan["rows"] = [r for r in plan["rows"] if not (r["week"] == 5 and r["exercise_id"] == "EX03")]
    r = _run(plan)
    assert _has(r, "evidence", "exercise_id", 5) and not _has(r, "evidence", "exercise_id", 4)


def test_high_intensity_run_not_required_when_run_goal_met():
    p = payload(difference_matrix=[[16, 18, 0, 0]],
                current_records={"pushups_2min": 48, "situps_2min": 60, "run_3km_seconds": 812})
    pi = validate_contract(p, CATALOG)
    plan = valid_plan()
    plan["rows"] = [r for r in plan["rows"] if r["exercise_id"] != "EX03"]
    assert not any(v.field == "exercise_id" for v in _run(plan, pi).violations)


def test_too_few_load_adaptation_weeks_is_flagged():
    plan = valid_plan()
    _row(plan, 4, "EX26").update(exercise_id="EX07", sets=3, reps=15, seconds=None)
    assert _has(_run(plan), "evidence", "exercise_id")


def test_week_without_recovery_exercise_is_flagged():
    plan = valid_plan()
    plan["rows"] = [r for r in plan["rows"] if not (r["week"] == 4 and r["exercise_id"] == "EX29")]
    assert _has(_run(plan), "volume", "recovery_exercises", 4)


# 5. evidence
def test_target_not_registered_is_flagged():
    plan = valid_plan()
    _row(plan, 1, "EX20")["targets"] = ["run_3km_seconds"]
    r = _run(plan)
    assert _has(r, "evidence", "targets", 1)


def test_evidence_not_registered_is_flagged():
    plan = valid_plan()
    _row(plan, 1, "EX20")["evidence_ids"] = ["EV03"]
    assert _has(_run(plan), "evidence", "evidence_ids", 1)


def test_coverage_missing_for_nonzero_delta_is_flagged():
    plan = valid_plan()
    plan["rows"] = [r for r in plan["rows"] if not (r["week"] == 6 and r["exercise_id"] == "EX14")]
    assert _has(_run(plan), "evidence", "targets", 6)


def test_coverage_not_required_when_goal_already_met():
    p = payload(difference_matrix=[[0, 18, -148, 0]],
                current_records={"pushups_2min": 64, "situps_2min": 60, "run_3km_seconds": 960})
    pi = validate_contract(p, CATALOG)
    plan = valid_plan()
    plan["summary"] = "윗몸일으키기 18회 증가와 3km 달리기 148초 단축을 목표로 한 8주 계획입니다."
    for r in plan["rows"]:
        if r["exercise_id"] == "EX20":
            r["reason"] = r["reason"].replace("16회 증가를 위해", "목표는 충족했으므로 유지를 위해")
    report = _run(plan, pi)
    assert report.passed, [v.model_dump() for v in report.violations]


# 6. explanation numbers
def test_reason_repeated_with_only_numbers_changed_is_flagged():
    plan = valid_plan()
    _row(plan, 2, "EX20")["reason"] = "팔굽혀펴기 16회 증가를 위해 3세트 17회를 합니다."
    _row(plan, 3, "EX20")["reason"] = "팔굽혀펴기 16회 증가를 위해 3세트 18회를 합니다."
    r = _run(plan)
    assert _has(r, "explanation", "reason", 3) and not _has(r, "explanation", "reason", 2)


def test_awkward_term_in_reason_is_flagged():
    plan = valid_plan()
    _row(plan, 6, "EX20")["reason"] += " 검사 횟수 범위까지 늘립니다."
    assert _has(_run(plan), "explanation", "reason", 6)


def test_sets_written_as_sessions_is_flagged():
    plan = valid_plan()
    _row(plan, 6, "EX20")["reason"] = "세트 3회, 21회로 늘립니다."
    r = _run(plan)
    assert _has(r, "explanation", "reason", 6)
    _row(plan, 6, "EX20")["reason"] = "3세트 21회로 늘립니다."
    assert not _has(_run(plan), "explanation", "reason", 6)


def test_rep_cap_number_is_allowed_in_reason():
    plan = valid_plan()
    _row(plan, 2, "EX20")["reason"] = "한 세트는 최대 28회를 넘기지 않도록 3세트 17회로 나눠 합니다."
    assert _run(plan).passed

def test_wrong_number_in_reason_is_flagged():
    plan = valid_plan()
    _row(plan, 2, "EX20")["reason"] = "팔굽혀펴기 20회 증가가 필요합니다."
    r = _run(plan)
    v = next(v for v in r.violations if v.check == "explanation")
    assert v.week == 2 and 20.0 in v.actual


def test_load_ratio_percent_only_allowed_with_percent_sign():
    plan = valid_plan()
    plan["summary"] += " 하중비는 체중의 20%로 참고 정보입니다."
    assert _run(plan).passed
    plan["summary"] += " 팔굽혀펴기는 매주 99회씩 늘립니다."
    assert _has(_run(plan), "explanation", "summary")


def test_reason_cannot_borrow_numbers_from_other_rows():
    plan = valid_plan()
    _row(plan, 6, "EX07")["reason"] = "하체 운동을 4회 실시합니다."
    assert _has(_run(plan), "explanation", "reason", 6)


def test_wrong_number_in_summary_is_flagged():
    plan = valid_plan()
    plan["summary"] = "3km 달리기 150초 단축이 목표입니다."
    assert _has(_run(plan), "explanation", "summary")


# 7. load usage
def test_load_ratio_as_score_is_flagged():
    plan = valid_plan()
    plan["summary"] += " 하중비 0.2로 보아 군장 능력이 부족합니다."
    assert _has(_run(plan), "load_usage", "summary")


def test_medical_expression_is_flagged():
    plan = valid_plan()
    _row(plan, 1, "EX29")["reason"] = "무릎 부상 예측 결과에 따라 준비운동을 합니다."
    assert _has(_run(plan), "load_usage", "reason", 1)
