"""코드 기반 계획 검증 (docs/PROJECT_SPEC.md 2.4).

LLM 없이 동작하는 순수 함수. 모든 기준값은 데이터 팩(catalog)에서 읽음.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from .catalog import Catalog
from .models import CHECKS, Plan, PlanInput, PlanRow, ValidationReport, Violation

PRESCRIPTION_FIELDS = ("sets", "reps", "seconds", "minutes", "load_kg")
# dose 형식별로 쓰는 처방 필드 (나머지는 null이어야 함).
DOSE_FIELDS = {
    "reps": ("sets", "reps"),
    "time": ("sets", "seconds"),
    "duration": ("minutes",),
    "ruck": ("minutes", "load_kg"),
}

_ID_PATTERN = re.compile(r"\b(?:EX|EV)\d+\b")
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def validate_plan(raw_plan: Any, plan_input: PlanInput, catalog: Catalog) -> ValidationReport:
    try:
        plan = Plan.model_validate(raw_plan)
    except ValidationError as e:
        violations = [
            Violation(
                check="structure",
                field=".".join(str(p) for p in err["loc"]),
                reason=f"plan does not match output schema: {err['msg']}",
            )
            for err in e.errors()
        ]
        return build_report(violations)

    violations: list[Violation] = []
    violations += check_structure(plan, catalog)
    violations += check_catalog_membership(plan, catalog)
    known_rows = [r for r in plan.rows if r.exercise_id in catalog.exercises]
    violations += check_volume(known_rows, catalog)
    violations += check_rep_cap(known_rows, plan_input, catalog)
    violations += check_conditions(known_rows, catalog)
    violations += check_evidence(known_rows, plan_input, catalog)
    violations += check_explanation(plan, plan_input, catalog)
    violations += check_load_usage(plan, catalog)
    return build_report(violations)


def build_report(violations: list[Violation]) -> ValidationReport:
    failed = {v.check for v in violations}
    return ValidationReport(
        passed=not violations,
        violations=violations,
        checks={c: ("fail" if c in failed else "pass") for c in CHECKS},
    )


def _rows_by_week(rows: list[PlanRow]) -> dict[int, list[PlanRow]]:
    out: dict[int, list[PlanRow]] = defaultdict(list)
    for r in rows:
        out[r.week].append(r)
    return out


# ---------- 1. 계획 구조 ----------


def check_structure(plan: Plan, catalog: Catalog) -> list[Violation]:
    n_weeks = catalog.rules["plan_weeks"]["value"]
    weeks = set(range(1, n_weeks + 1))
    out: list[Violation] = []
    by_week = _rows_by_week(plan.rows)
    for w in sorted(weeks - set(by_week)):
        out.append(Violation(check="structure", week=w, field="week", allowed=f"1..{n_weeks}",
                             reason=f"week {w} has no exercises"))
    for w in sorted(set(by_week) - weeks):
        out.append(Violation(check="structure", week=w, field="week", allowed=f"1..{n_weeks}", actual=w,
                             reason=f"week {w} is outside the {n_weeks}-week plan"))
    seen: set[tuple[int, str]] = set()
    for r in plan.rows:
        key = (r.week, r.exercise_id)
        if key in seen:
            out.append(Violation(check="structure", week=r.week, exercise_id=r.exercise_id, field="exercise_id",
                                 reason="same exercise appears twice in one week; merge into one row"))
        seen.add(key)
    return out


# ---------- 2. 운동 목록 ----------


def check_catalog_membership(plan: Plan, catalog: Catalog) -> list[Violation]:
    return [
        Violation(check="catalog", week=r.week, exercise_id=r.exercise_id, field="exercise_id",
                  allowed="EX01..EX30 in exercises catalog", actual=r.exercise_id,
                  reason="exercise is not in the registered exercise list")
        for r in plan.rows
        if r.exercise_id not in catalog.exercises
    ]


# ---------- 3. 운동량·빈도 ----------


def _in_range(value: float, rng: list[float]) -> bool:
    return rng[0] <= value <= rng[1]


def row_volume(row: PlanRow, ex: dict[str, Any]) -> tuple[int, int]:
    """한 행이 주간 총량에 더하는 (세트, 분). 회복 운동은 0으로 계산."""
    if ex["category"] == "recovery":
        return 0, 0
    t = ex["dose"]["type"]
    if t in ("reps", "time"):
        return row.sessions_per_week * (row.sets or 0), 0
    return 0, row.sessions_per_week * (row.minutes or 0)


def check_volume(rows: list[PlanRow], catalog: Catalog) -> list[Violation]:
    rules = catalog.rules
    out: list[Violation] = []

    for r in rows:
        ex = catalog.exercises[r.exercise_id]
        dose = ex["dose"]
        used = DOSE_FIELDS[dose["type"]]
        freq = ex["frequency_per_week"]
        if not _in_range(r.sessions_per_week, freq):
            out.append(Violation(check="volume", week=r.week, exercise_id=r.exercise_id, field="sessions_per_week",
                                 allowed=freq, actual=r.sessions_per_week,
                                 reason="sessions per week outside the exercise's allowed range"))
        for f in PRESCRIPTION_FIELDS:
            val = getattr(r, f)
            if f in used:
                if val is None:
                    out.append(Violation(check="volume", week=r.week, exercise_id=r.exercise_id, field=f,
                                         allowed=dose[f], actual=None,
                                         reason=f"dose type '{dose['type']}' requires {f}"))
                elif not _in_range(val, dose[f]):
                    out.append(Violation(check="volume", week=r.week, exercise_id=r.exercise_id, field=f,
                                         allowed=dose[f], actual=val,
                                         reason=f"{f} outside the exercise's allowed range"))
            elif val is not None:
                out.append(Violation(check="volume", week=r.week, exercise_id=r.exercise_id, field=f,
                                     allowed=None, actual=val,
                                     reason=f"dose type '{dose['type']}' does not use {f}; set it to null"))

    per_week = rules["exercises_per_week"]
    caps = rules["weekly_caps"]
    prog = rules["weekly_progression"]
    by_week = _rows_by_week(rows)
    totals: dict[int, tuple[int, int]] = {}
    for w in sorted(by_week):
        wrows = by_week[w]
        if not (per_week["min"] <= len(wrows) <= per_week["max"]):
            out.append(Violation(check="volume", week=w, field="exercises_per_week",
                                 allowed=[per_week["min"], per_week["max"]], actual=len(wrows),
                                 reason="number of exercises in the week outside the allowed range"))
        sets = sum(row_volume(r, catalog.exercises[r.exercise_id])[0] for r in wrows)
        minutes = sum(row_volume(r, catalog.exercises[r.exercise_id])[1] for r in wrows)
        totals[w] = (sets, minutes)
        rec = rules["recovery_per_week"]
        n_rec = sum(1 for r in wrows if catalog.exercises[r.exercise_id]["category"] == rec["category"])
        if n_rec < rec["min_exercises"]:
            out.append(Violation(check="volume", week=w, field="recovery_exercises",
                                 allowed=f">= {rec['min_exercises']} {rec['category']} exercise(s)", actual=n_rec,
                                 reason="each week needs a recovery exercise"))
        if sets > caps["max_total_sets"]:
            out.append(Violation(check="volume", week=w, field="weekly_total_sets",
                                 allowed=f"<= {caps['max_total_sets']}", actual=sets,
                                 reason="weekly total sets (sessions x sets) exceeds cap"))
        if minutes > caps["max_total_minutes"]:
            out.append(Violation(check="volume", week=w, field="weekly_total_minutes",
                                 allowed=f"<= {caps['max_total_minutes']}", actual=minutes,
                                 reason="weekly total minutes (sessions x minutes) exceeds cap"))

    for w in sorted(totals):
        if w - 1 not in totals:
            continue
        for idx, name, allowance in ((0, "sets", prog["min_allowance_sets"]),
                                     (1, "minutes", prog["min_allowance_minutes"])):
            prev, cur = totals[w - 1][idx], totals[w][idx]
            limit = max(prev * prog["max_increase_ratio"], prev + allowance)
            if cur > limit + 1e-9:
                out.append(Violation(check="volume", week=w, field=f"weekly_total_{name}",
                                     allowed=f"<= {limit:g} (week {w - 1} total {prev})", actual=cur,
                                     reason=f"weekly total {name} increased too fast from the previous week"))

    last = rules["plan_weeks"]["value"]
    if rules["final_week_taper"]["enabled"] and last in totals and last - 1 in totals:
        for idx, name in ((0, "sets"), (1, "minutes")):
            prev, cur = totals[last - 1][idx], totals[last][idx]
            if cur > prev:
                out.append(Violation(check="volume", week=last, field=f"weekly_total_{name}",
                                     allowed=f"<= {prev} (week {last - 1} total)", actual=cur,
                                     reason=f"final week total {name} must not exceed the previous week (ease off before the test)"))
    return out


def rep_cap(exercise_id: str, plan_input: PlanInput, catalog: Catalog) -> int | None:
    """검정 종목 운동의 1세트 최대 횟수. 대상 운동이 아니면 None."""
    rule = catalog.rules["rep_cap_by_record"]
    record = rule["exercise_to_record"].get(exercise_id)
    if record is None:
        return None
    current = getattr(plan_input.payload.current_records, record)
    dose_min = catalog.exercises[exercise_id]["dose"]["reps"][0]
    return max(math.floor(current * rule["max_ratio_of_current"]), dose_min)


def rep_caps(plan_input: PlanInput, catalog: Catalog) -> dict[str, int]:
    ids = catalog.rules["rep_cap_by_record"]["exercise_to_record"]
    return {ex_id: rep_cap(ex_id, plan_input, catalog) for ex_id in ids}


def check_rep_cap(rows: list[PlanRow], plan_input: PlanInput, catalog: Catalog) -> list[Violation]:
    ratio = catalog.rules["rep_cap_by_record"]["max_ratio_of_current"]
    out: list[Violation] = []
    for r in rows:
        cap = rep_cap(r.exercise_id, plan_input, catalog)
        if cap is not None and r.reps is not None and r.reps > cap:
            out.append(Violation(check="volume", week=r.week, exercise_id=r.exercise_id, field="reps",
                                 allowed=f"<= {cap}", actual=r.reps,
                                 reason=f"reps per set above {ratio:g} x the soldier's current record"))
    return out


# ---------- 4. 적용 조건 ----------


def _max_difficulty(week: int, catalog: Catalog) -> int | None:
    for rule in catalog.rules["difficulty_by_week"]["rules"]:
        lo, hi = rule["weeks"]
        if lo <= week <= hi:
            return rule["max_difficulty"]
    return None


def check_conditions(rows: list[PlanRow], catalog: Catalog) -> list[Violation]:
    out: list[Violation] = []
    allowed_eq = set(catalog.rules["allowed_equipment"]["value"])
    ruck = catalog.rules["ruck"]
    excluded = catalog.rules["excluded_exercises"]["value"]
    for r in rows:
        ex = catalog.exercises[r.exercise_id]
        if r.exercise_id in excluded:
            out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="exercise_id",
                                 allowed=f"not in {excluded}", actual=r.exercise_id,
                                 reason="exercise is excluded from plans under the current rules"))
        max_d = _max_difficulty(r.week, catalog)
        if max_d is not None and ex["difficulty"] > max_d:
            out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="difficulty",
                                 allowed=f"<= {max_d}", actual=ex["difficulty"],
                                 reason=f"difficulty too high for week {r.week}"))
        min_week = ex["restrictions"]["min_week"]
        if r.week < min_week:
            out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="week",
                                 allowed=f">= {min_week}", actual=r.week,
                                 reason="exercise not allowed before its minimum week"))
        bad_eq = [e for e in ex["equipment"] if e not in allowed_eq]
        if bad_eq:
            out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="equipment",
                                 allowed=sorted(allowed_eq), actual=bad_eq,
                                 reason="exercise requires equipment that is not allowed"))
        if r.exercise_id in ruck["exercise_ids"]:
            if r.week < ruck["min_week"]:
                out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="week",
                                     allowed=f">= {ruck['min_week']}", actual=r.week,
                                     reason="rucksack walking only from the allowed start week"))
            if r.sessions_per_week > ruck["max_sessions_per_week"]:
                out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id,
                                     field="sessions_per_week", allowed=f"<= {ruck['max_sessions_per_week']}",
                                     actual=r.sessions_per_week, reason="too many rucksack sessions per week"))
            if r.load_kg is not None and r.load_kg > ruck["max_load_kg"]:
                out.append(Violation(check="conditions", week=r.week, exercise_id=r.exercise_id, field="load_kg",
                                     allowed=f"<= {ruck['max_load_kg']}", actual=r.load_kg,
                                     reason="rucksack load above the fixed combat load"))
    return out


# ---------- 5. 추천 근거 ----------


def check_evidence(rows: list[PlanRow], plan_input: PlanInput, catalog: Catalog) -> list[Violation]:
    out: list[Violation] = []
    for r in rows:
        ex = catalog.exercises[r.exercise_id]
        if not r.targets:
            out.append(Violation(check="evidence", week=r.week, exercise_id=r.exercise_id, field="targets",
                                 allowed=ex["related_tests"], actual=[], reason="targets must not be empty"))
        bad_t = [t for t in r.targets if t not in ex["related_tests"]]
        if bad_t:
            out.append(Violation(check="evidence", week=r.week, exercise_id=r.exercise_id, field="targets",
                                 allowed=ex["related_tests"], actual=bad_t,
                                 reason="targets not registered for this exercise"))
        if not r.evidence_ids:
            out.append(Violation(check="evidence", week=r.week, exercise_id=r.exercise_id, field="evidence_ids",
                                 allowed=ex["evidence_ids"], actual=[], reason="evidence_ids must not be empty"))
        bad_e = [e for e in r.evidence_ids if e not in ex["evidence_ids"]]
        if bad_e:
            out.append(Violation(check="evidence", week=r.week, exercise_id=r.exercise_id, field="evidence_ids",
                                 allowed=ex["evidence_ids"], actual=bad_e,
                                 reason="evidence_ids not registered for this exercise"))

    cov = catalog.rules["coverage"]
    n_weeks = catalog.rules["plan_weeks"]["value"]
    by_week = _rows_by_week(rows)
    if cov["every_week_for_nonzero_delta"]:
        for col in plan_input.nonzero_columns:
            for w in range(1, n_weeks + 1):
                if not any(col in r.targets for r in by_week.get(w, [])):
                    out.append(Violation(check="evidence", week=w, field="targets", allowed=f"includes {col}",
                                         reason=f"{col} needs improvement but no exercise targets it this week"))
    lc_weeks = sum(1 for w in range(1, n_weeks + 1)
                   if any("load_carriage" in r.targets for r in by_week.get(w, [])))
    if lc_weeks < cov["min_weeks_with_load_carriage"]:
        out.append(Violation(check="evidence", field="targets",
                             allowed=f">= {cov['min_weeks_with_load_carriage']} weeks targeting load_carriage",
                             actual=lc_weeks, reason="secondary goal (15kg load readiness) is under-covered"))
    la_cat = cov["load_adaptation_category"]
    la_weeks = sum(1 for w in range(1, n_weeks + 1)
                   if any(catalog.exercises[r.exercise_id]["category"] == la_cat for r in by_week.get(w, [])))
    if la_weeks < cov["min_weeks_with_load_adaptation"]:
        out.append(Violation(check="evidence", field="exercise_id",
                             allowed=f">= {cov['min_weeks_with_load_adaptation']} weeks with a {la_cat} exercise",
                             actual=la_weeks, reason="too few weeks with a load adaptation exercise (carry or stairs)"))

    rq = catalog.rules["run_quality"]
    if rq["when_column_needs_improvement"] in plan_input.nonzero_columns:
        for w in range(rq["from_week"], n_weeks + 1):
            n = sum(1 for r in by_week.get(w, []) if r.exercise_id in rq["exercise_ids"])
            if n < rq["min_per_week"]:
                out.append(Violation(check="evidence", week=w, field="exercise_id",
                                     allowed=f">= {rq['min_per_week']} of {rq['exercise_ids']}", actual=n,
                                     reason="3km needs improvement but this week has no high-intensity run"))
    return out


# ---------- 6. 설명 수치 ----------


def _variants(x: float) -> set[float]:
    return {round(x, 0), round(x, 1), round(x, 2), round(x, 3)}


def global_allowed_numbers(plan_input: PlanInput, catalog: Catalog) -> set[float]:
    p = plan_input.payload
    vals: list[float] = list(catalog.rules["explanation"]["allowed_constants"])
    for n in plan_input.needs:
        vals += [n.delta, n.amount]
    for rec in (p.current_records, p.goal_records):
        vals += [rec.pushups_2min, rec.situps_2min, rec.run_3km_seconds]
    s = p.soldier
    vals += [s.height_cm, s.weight_kg, s.age]
    if s.bmi is not None:
        vals.append(s.bmi)
    vals += [p.load_context.combat_load_kg, p.load_context.load_to_body_weight_ratio]
    vals += [c for c in rep_caps(plan_input, catalog).values()]
    out: set[float] = set()
    for v in vals:
        out |= _variants(abs(float(v)))
    return out


def percent_allowed_numbers(plan_input: PlanInput) -> set[float]:
    """'%'를 붙여 쓸 때만 허용되는 숫자 (하중비의 백분율 표기)."""
    return _variants(plan_input.payload.load_context.load_to_body_weight_ratio * 100)


def extract_numbers(text: str) -> list[tuple[float, bool]]:
    """EX/EV ID를 제외한 모든 숫자를 (값, 백분율 여부)로 추출."""
    clean = _ID_PATTERN.sub(" ", text)
    return [(float(m.group()), clean[m.end():m.end() + 1] == "%") for m in _NUMBER_PATTERN.finditer(clean)]


def _bad_numbers(text: str, allowed: set[float], percent_allowed: set[float]) -> list[float]:
    bad = []
    for value, is_percent in extract_numbers(text):
        pool = percent_allowed if is_percent else allowed
        if round(value, 3) not in pool:
            bad.append(value)
    return bad


def _row_numbers(r: PlanRow) -> set[float]:
    vals = [r.week, r.sessions_per_week] + [getattr(r, f) for f in PRESCRIPTION_FIELDS]
    out: set[float] = set()
    for v in vals:
        if v is not None:
            out |= _variants(float(v))
    return out


def check_explanation(plan: Plan, plan_input: PlanInput, catalog: Catalog) -> list[Violation]:
    out: list[Violation] = []
    base = global_allowed_numbers(plan_input, catalog)
    pct = percent_allowed_numbers(plan_input)
    for r in plan.rows:
        bad = _bad_numbers(r.reason, base | _row_numbers(r), pct)
        if bad:
            out.append(Violation(check="explanation", week=r.week, exercise_id=r.exercise_id, field="reason",
                                 actual=bad, allowed="deltas, records, soldier info, this row's prescription",
                                 reason="reason contains numbers that do not match the provided data"))
    summary_allowed = set(base)
    for w in range(1, catalog.rules["plan_weeks"]["value"] + 1):
        summary_allowed |= _variants(float(w))
    for r in plan.rows:
        summary_allowed |= _row_numbers(r)
    bad = _bad_numbers(plan.summary, summary_allowed, pct)
    if bad:
        out.append(Violation(check="explanation", field="summary", actual=bad,
                             allowed="deltas, records, soldier info, plan prescriptions",
                             reason="summary contains numbers that do not match the provided data"))

    rule = catalog.rules["explanation"]
    for row, field, text in _texts(plan):
        for term in rule["discouraged_terms"]:
            if term in text:
                out.append(Violation(check="explanation", week=row.week if row else None,
                                     exercise_id=row.exercise_id if row else None, field=field, actual=term,
                                     reason=f"awkward or internal term '{term}'; rewrite in plain Korean"))
        for pattern in rule["discouraged_patterns"]:
            m = re.search(pattern, text)
            if m:
                out.append(Violation(check="explanation", week=row.week if row else None,
                                     exercise_id=row.exercise_id if row else None, field=field, actual=m.group(),
                                     reason="write sets as 'N세트 M회' (e.g. '4세트 28회'); "
                                            "'세트 N회' is confused with sessions per week"))
    if rule["unique_reasons_per_exercise"]:
        first_week: dict[tuple[str, str], int] = {}
        for r in sorted(plan.rows, key=lambda r: r.week):
            key = (r.exercise_id, _NUMBER_PATTERN.sub("#", re.sub(r"\s+", " ", r.reason.strip())))
            if key in first_week:
                out.append(Violation(check="explanation", week=r.week, exercise_id=r.exercise_id, field="reason",
                                     actual=r.reason,
                                     reason=f"same reason as week {first_week[key]} for this exercise "
                                            "(only numbers differ); explain what changes this week and why"))
            else:
                first_week[key] = r.week
    return out


# ---------- 7. 하중 정보 활용 ----------


def _texts(plan: Plan) -> list[tuple[PlanRow | None, str, str]]:
    return [(None, "summary", plan.summary)] + [(r, "reason", r.reason) for r in plan.rows]


def check_load_usage(plan: Plan, catalog: Catalog) -> list[Violation]:
    rule = catalog.rules["explanation"]
    out: list[Violation] = []
    for row, field, text in _texts(plan):
        loc = {"week": row.week if row else None, "exercise_id": row.exercise_id if row else None, "field": field}
        for term in rule["forbidden_terms"]:
            if term in text:
                out.append(Violation(check="load_usage", actual=term, allowed="no medical expressions",
                                     reason=f"forbidden expression '{term}'", **loc))
        for sentence in _SENTENCE_SPLIT.split(text):
            if any(t in sentence for t in rule["load_ratio_terms"]):
                misuse = [m for m in rule["load_ratio_misuse_terms"] if m in sentence]
                if misuse:
                    out.append(Violation(check="load_usage", actual=sentence.strip(),
                                         allowed="load ratio may only be mentioned as reference information",
                                         reason=f"load ratio used as an evaluation ({', '.join(misuse)})", **loc))
    return out
