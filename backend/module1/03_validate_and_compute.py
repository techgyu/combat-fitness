#!/usr/bin/env python3
"""Stage 03: validate synthetic soldier records, then compute BMI/load ratio.

Python 3.10+, standard library only. Run beside this file:
    python 03_validate_and_compute.py
    python 03_validate_and_compute.py --input data/synthetic_soldiers.csv
    python 03_validate_and_compute.py --self-test

One current-run report is replaced atomically, including on validation failure.
Input files are never modified. A failed report always has records=[].
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

VERSION = "2.0.0"
DATA_DIR = Path(__file__).resolve().parent / "data"
AGE_BASIS = "calendar_year_minus_birth_year"
LOAD_KG = 15.0
# Broad DEMO input guards, NOT military eligibility or medical standards.
BOUNDS = {
    "age": (18, 29),
    "height_cm": (100, 250),
    "weight_kg": (20, 350),
    "run_3km_seconds": (60, 7200),
}
SECONDS_UNITS = {"s", "sec", "second", "seconds"}
MINUTES_UNITS = {"min", "minute", "minutes"}


class InputError(ValueError):
    """An expected, actionable input problem."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def number(value, *, integer=False, lower=None, upper=None):
    if missing(value):
        raise InputError("missing", "필수 숫자값이 없습니다.")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InputError("type", "숫자를 입력해야 합니다. 참/거짓은 숫자로 받지 않습니다.")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise InputError("type", "단위 문자를 붙이지 않은 숫자가 필요합니다.") from None
    if not math.isfinite(result):
        raise InputError("non_finite", "NaN 또는 무한대는 사용할 수 없습니다.")
    if integer and not result.is_integer():
        raise InputError("integer", "정수만 사용할 수 있습니다.")
    if lower is not None and result < lower:
        raise InputError("range_or_unit", f"{lower} 이상이어야 합니다. 값과 단위를 확인하세요.")
    if upper is not None and result > upper:
        raise InputError("range_or_unit", f"{upper} 이하여야 합니다. 값과 단위를 확인하세요.")
    return int(result) if integer else result


def unit(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError("unit", "단위를 문자열로 명시해야 합니다.")
    return value.strip().lower()


def run_seconds(row: dict):
    """Never infer a numeric time's unit from its magnitude."""
    direct = not missing(row.get("run_3km_seconds"))
    alternate = not missing(row.get("run_3km_time"))
    if direct and alternate:
        raise InputError("ambiguous_time", "run_3km_seconds와 run_3km_time 중 하나만 입력하세요.")
    if not direct and not alternate:
        raise InputError("missing", "3km 달리기 기록이 없습니다.")
    declared = unit(row["run_3km_unit"]) if "run_3km_unit" in row else None
    if direct:
        if declared is not None and declared not in SECONDS_UNITS:
            raise InputError("unit", "run_3km_seconds의 단위는 초(s)여야 합니다.")
        seconds = number(row["run_3km_seconds"])
    else:
        value = row["run_3km_time"]
        if isinstance(value, str) and ":" in value:
            match = re.fullmatch(r"(\d{1,3}):([0-5]\d)", value.strip())
            if not match:
                raise InputError("time_format", "분:초 형식은 MM:SS이며 초 부분은 00~59입니다.")
            if declared not in (None, "mm:ss"):
                raise InputError("unit", "분:초 문자열의 단위는 생략하거나 mm:ss로 지정하세요.")
            seconds = int(match[1]) * 60 + int(match[2])
        else:
            if declared not in SECONDS_UNITS | MINUTES_UNITS:
                raise InputError("unit", "숫자형 run_3km_time에는 s 또는 min 단위가 필요합니다.")
            seconds = number(value)
            if declared in MINUTES_UNITS:
                seconds *= 60
    seconds = number(seconds, lower=BOUNDS["run_3km_seconds"][0],
                     upper=BOUNDS["run_3km_seconds"][1])
    return int(seconds) if seconds.is_integer() else seconds


def issue(row_number, soldier_id, field, code, message) -> dict:
    return {
        "row": row_number, "soldier_id": soldier_id, "field": field,
        "code": code, "message": message,
    }


def validate_record(raw, row_number: int) -> tuple[dict, list[dict]]:
    if not isinstance(raw, dict):
        return {}, [issue(row_number, None, "$record", "type",
                          "장병 한 명은 JSON 객체여야 합니다.")]
    normalized = {}
    errors = []
    for legacy in ("pushups_1min", "situps_1min", "pushups_60s", "situps_60s"):
        if legacy in raw:
            errors.append(issue(row_number, raw.get("soldier_id"), legacy, "legacy_protocol",
                                "1분 기록은 처리하지 않습니다. 2분 조건의 데이터를 다시 생성하세요."))
    if "record_schema_version" in raw and raw["record_schema_version"] != "2.0":
        errors.append(issue(row_number, raw.get("soldier_id"), "record_schema_version",
                            "schema_version", "record_schema_version은 2.0이어야 합니다."))
    label = raw.get("soldier_id") if isinstance(raw.get("soldier_id"), str) else None

    def capture(field, operation):
        try:
            normalized[field] = operation()
        except InputError as exc:
            errors.append(issue(row_number, label, field, exc.code, str(exc)))

    def text_value(field, expected=None):
        value = raw.get(field)
        if missing(value):
            raise InputError("missing", "필수 문자열이 없습니다.")
        if not isinstance(value, str):
            raise InputError("type", "문자열이어야 합니다.")
        value = value.strip()
        if expected is not None and value != expected:
            raise InputError("fixed_condition", f"이 시연에서는 {expected!r}로 고정합니다.")
        return value

    capture("soldier_id", lambda: text_value("soldier_id"))
    if "soldier_id" in normalized and not re.fullmatch(r"[0-9]{2}-[0-9]{8}", normalized["soldier_id"]):
        errors.append(issue(row_number, label, "soldier_id", "service_number_format",
                            "군번은 26-00000001처럼 연도 2자리-숫자 8자리여야 합니다."))
    capture("sex", lambda: text_value("sex", "male"))
    capture("role", lambda: text_value("role", "infantry_rifleman"))
    for field in ("age", "height_cm", "weight_kg"):
        capture(field, lambda field=field: number(
            raw.get(field), integer=(field == "age"),
            lower=BOUNDS[field][0], upper=BOUNDS[field][1],
        ))
    for field in ("pushups_2min", "situps_2min"):
        capture(field, lambda field=field: number(raw.get(field), integer=True, lower=0))
    capture("combat_load_kg", lambda: number(raw.get("combat_load_kg"),
                                            lower=LOAD_KG, upper=LOAD_KG))
    capture("run_3km_seconds", lambda: run_seconds(raw))

    # Require explicit synthetic provenance; CSV serializes True as a string.
    synthetic = raw.get("is_synthetic")
    if synthetic is True or (isinstance(synthetic, str) and synthetic.strip().lower() == "true"):
        normalized["is_synthetic"] = True
    else:
        errors.append(issue(row_number, label, "is_synthetic", "fixed_condition",
                            "합성 데이터 표시 is_synthetic=true가 필요합니다."))
    if "age_basis" in raw:
        capture("age_basis", lambda: text_value("age_basis", AGE_BASIS))
    else:
        normalized["age_basis"] = AGE_BASIS
    # Existing BMI is optional; valid numeric values are checked again after
    # the entire batch passes base-field validation.
    if not missing(raw.get("bmi")):
        capture("bmi", lambda: number(raw["bmi"], lower=0.01))
    for field in ("body_reference_group", "fitness_scenario"):
        if field in raw:
            capture(field, lambda field=field: text_value(field))

    # Units are encoded in the canonical field names. Explicit conflicting
    # declarations, if present, must fail instead of being silently ignored.
    for field, expected in (
        ("height_unit", "cm"), ("weight_unit", "kg"), ("combat_load_unit", "kg"),
    ):
        if field in raw:
            try:
                if unit(raw[field]) != expected:
                    raise InputError("unit", f"이 필드는 {expected} 단위로 입력하세요.")
            except InputError as exc:
                errors.append(issue(row_number, label, field, exc.code, str(exc)))
    for field, expected in (
        ("pushups_duration_seconds", 120), ("situps_duration_seconds", 120),
        ("run_distance_m", 3000), ("baseline_test_load_kg", 0),
    ):
        if field in raw:
            try:
                number(raw[field], lower=expected, upper=expected)
            except InputError as exc:
                errors.append(issue(row_number, label, field, exc.code, str(exc)))
    normalized["record_schema_version"] = "2.0"
    normalized["pushups_duration_seconds"] = 120
    normalized["situps_duration_seconds"] = 120
    normalized["run_distance_m"] = 3000
    normalized["baseline_test_load_kg"] = 0
    return normalized, errors


def validate_and_compute(records) -> dict:
    report = {
        "schema_version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "summary": {
            "total_records": 0, "valid_records": 0, "invalid_records": 0,
            "computed_records": 0, "error_count": 0, "warning_count": 0,
        },
        "units": {
            "age": AGE_BASIS, "height_cm": "cm", "weight_kg": "kg",
            "bmi": "kg/m^2", "combat_load_kg": "kg",
            "pushups_2min": "repetitions/120s", "situps_2min": "repetitions/120s",
            "run_3km_seconds": "s", "load_ratio": "dimensionless",
            "load_ratio_percent": "%",
        },
        "validation_policy": {
            "version": VERSION, "bounds": BOUNDS,
            "bounds_basis": "demo_input_guards_not_eligibility_or_medical_standards",
            "combat_load_kg": LOAD_KG, "baseline_test_load_kg": 0,
            "bmi": "recompute_from_height_and_weight; warn_if_difference_gt_0.05",
            "batch_policy": "any_error_prevents_all_computed_records",
        },
        "records": [], "errors": [], "warnings": [],
    }
    errors = report["errors"]
    if not isinstance(records, list):
        errors.append(issue(None, None, "$input", "type", "입력 JSON의 최상위는 배열이어야 합니다."))
    elif not records:
        errors.append(issue(None, None, "$input", "empty", "장병 데이터가 비어 있습니다."))
    else:
        report["summary"]["total_records"] = len(records)
        normalized = []
        ids = {}
        for row_number, raw in enumerate(records, 1):
            row, row_errors = validate_record(raw, row_number)
            errors.extend(row_errors)
            identifier = row.get("soldier_id")
            if identifier is not None:
                if identifier in ids:
                    errors.append(issue(row_number, identifier, "soldier_id", "duplicate_id",
                                        f"{ids[identifier]}번째 장병과 ID가 중복됩니다."))
                else:
                    ids[identifier] = row_number
            normalized.append(row)
        invalid_rows = {error["row"] for error in errors if error["row"] is not None}
        report["summary"]["invalid_records"] = len(invalid_rows)
        report["summary"]["valid_records"] = len(records) - len(invalid_rows)
        # No BMI/load calculation until every input row has passed validation.
        if not errors:
            for row_number, row in enumerate(normalized, 1):
                bmi = round(row["weight_kg"] / (row["height_cm"] / 100) ** 2, 2)
                previous = row.get("bmi")
                if previous is not None and abs(previous - bmi) > 0.050000001:
                    report["warnings"].append(issue(
                        row_number, row["soldier_id"], "bmi", "bmi_recomputed",
                        f"기존 BMI {previous}를 키·체중으로 재계산한 {bmi}로 교체했습니다.",
                    ))
                row["bmi"] = bmi
                ratio = LOAD_KG / row["weight_kg"]
                row["load_ratio"] = round(ratio, 6)
                row["load_ratio_percent"] = round(ratio * 100, 2)
            report["status"] = "passed"
            report["records"] = normalized
            report["summary"]["computed_records"] = len(normalized)
    report["summary"]["error_count"] = len(errors)
    report["summary"]["warning_count"] = len(report["warnings"])
    return report


def reject_constant(value):
    raise InputError("non_finite", f"JSON에 비표준 숫자 {value}가 있습니다.")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate_key", f"JSON 키 {key!r}가 중복되었습니다.")
        result[key] = value
    return result


def load_records(path: Path) -> tuple[object, str]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    content = payload.decode("utf-8-sig")
    if path.suffix.lower() == ".json":
        return json.loads(content, parse_constant=reject_constant,
                          object_pairs_hook=unique_object), digest
    if path.suffix.lower() != ".csv":
        raise InputError("file_format", "입력 확장자는 .json 또는 .csv여야 합니다.")
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    headers = reader.fieldnames
    if not headers or any(not header for header in headers) or len(headers) != len(set(headers)):
        raise InputError("csv_header", "CSV 헤더가 비었거나 중복되었습니다.")
    records = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise InputError("csv_columns", f"CSV {reader.line_num}행의 열 수가 헤더와 다릅니다.")
        records.append(row)
    return records, digest


def write_report(report: dict, output: Path) -> None:
    """Replace just this report; never expose half-written JSON to consumers."""
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def process_file(input_path: Path, output_path: Path) -> dict:
    source, target = input_path.resolve(), output_path.resolve()
    if source == target or (source.exists() and target.exists() and source.samefile(target)):
        raise InputError("output_path", "출력 경로는 입력 파일과 달라야 합니다.")
    digest = None
    try:
        records, digest = load_records(source)
    except (OSError, UnicodeError, ValueError, csv.Error, RecursionError) as exc:
        report = validate_and_compute([])
        report["errors"] = [issue(None, None, "$input",
                                  getattr(exc, "code", "input_read"), str(exc))]
        report["summary"]["error_count"] = 1
    else:
        report = validate_and_compute(records)
    report["source"] = {"input_path": str(source), "sha256": digest}
    write_report(report, target)
    return report


class ValidationTests(unittest.TestCase):
    @staticmethod
    def sample(**updates):
        row = {
            "soldier_id": "26-00000001", "is_synthetic": True, "age": 21,
            "age_basis": AGE_BASIS, "sex": "male", "role": "infantry_rifleman",
            "height_cm": 175.0, "weight_kg": 75.0, "bmi": 24.49,
            "combat_load_kg": 15.0, "pushups_2min": 40, "situps_2min": 45,
            "run_3km_seconds": 1110,
        }
        row.update(updates)
        return row

    def test_normal_values_and_zero_repetitions(self):
        original = self.sample(pushups_2min=0, situps_2min=0)
        report = validate_and_compute([original])
        self.assertEqual(report["status"], "passed")
        row = report["records"][0]
        self.assertEqual((row["bmi"], row["load_ratio"], row["load_ratio_percent"]),
                         (24.49, 0.2, 20.0))
        self.assertNotIn("load_ratio", original)

    def test_missing_or_stale_bmi_is_recomputed(self):
        for supplied in (None, 99):
            report = validate_and_compute([self.sample(bmi=supplied)])
            self.assertEqual(report["records"][0]["bmi"], 24.49)
            self.assertEqual(len(report["warnings"]), int(supplied is not None))

    def test_run_representations(self):
        for value, declaration in (("18:30", None), (18.5, "min"), ("1110", "s")):
            raw = self.sample()
            del raw["run_3km_seconds"]
            raw["run_3km_time"] = value
            if declaration is not None:
                raw["run_3km_unit"] = declaration
            report = validate_and_compute([raw])
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["records"][0]["run_3km_seconds"], 1110)
            self.assertNotIn("run_3km_time", report["records"][0])

    def test_bad_fields_stop_whole_batch(self):
        cases = (
            {"height_cm": None}, {"height_cm": 1.75}, {"weight_kg": 75000},
            {"weight_kg": 0}, {"age": 30}, {"age": True}, {"pushups_2min": -1},
            {"situps_2min": 1.5}, {"weight_kg": float("nan")},
            {"bmi": float("inf")}, {"combat_load_kg": 20}, {"sex": "female"},
            {"is_synthetic": False}, {"height_unit": "m"},
            {"pushups_duration_seconds": 60}, {"baseline_test_load_kg": 15},
            {"run_3km_seconds": 18.5}, {"run_3km_unit": "min"},
            {"run_3km_time": "18:30"},  # Conflicts with the seconds field.
        )
        for changes in cases:
            with self.subTest(changes=changes):
                report = validate_and_compute([
                    self.sample(), self.sample(soldier_id="26-00000002", **changes),
                ])
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["records"], [])
                self.assertEqual(report["summary"]["computed_records"], 0)
                self.assertEqual(report["errors"][0]["row"], 2)

    def test_bad_time_formats_and_unspecified_unit(self):
        for value, declaration in (("18:60", None), ("18:3", None),
                                   (18.5, None), ("18:30", "min")):
            row = self.sample()
            del row["run_3km_seconds"]
            row["run_3km_time"] = value
            if declaration:
                row["run_3km_unit"] = declaration
            self.assertEqual(validate_and_compute([row])["status"], "failed")

    def test_bad_structure_and_duplicate_id(self):
        for records in ([], {}, [None], [self.sample(), self.sample()]):
            report = validate_and_compute(records)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["records"], [])

    def test_csv_and_failure_replaces_previous_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.csv"
            target = Path(directory) / "result.json"
            row = self.sample()
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            report = process_file(source, target)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["records"][0]["load_ratio"], 0.2)
            unchanged_input = source.read_bytes()
            with self.assertRaises(InputError):
                process_file(source, source)
            self.assertEqual(source.read_bytes(), unchanged_input)
            source.write_text("age,age\n20,21\n", encoding="utf-8")
            self.assertEqual(process_file(source, target)["status"], "failed")
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["records"], [])
            source.unlink()
            self.assertEqual(process_file(source, target)["status"], "failed")

    def test_json_parser_rejects_nonstandard_or_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            target = Path(directory) / "result.json"
            for content in ('[{"weight_kg": NaN}]', '[{"age":20,"age":21}]', "{"):
                source.write_text(content, encoding="utf-8")
                self.assertEqual(process_file(source, target)["status"], "failed")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="합성 장병 입력 검증 및 BMI·하중비 계산")
    parser.add_argument("--input", type=Path, default=DATA_DIR / "synthetic_soldiers.json")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "validation_result.json",
                        help="매 실행의 통합 결과 JSON. 기존 결과를 교체합니다.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ValidationTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    try:
        report = process_file(args.input, args.output)
    except (OSError, ValueError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        print("현재 실행의 결과 저장에 실패했습니다. 기존 결과를 이번 실행 결과로 사용하지 마세요.",
              file=sys.stderr)
        return 2
    summary = report["summary"]
    if report["status"] == "passed":
        print(f"검증 통과: {summary['computed_records']}명 / BMI·하중비 계산 완료")
    else:
        print(f"검증 실패: 오류 {summary['error_count']}건 / 계산 결과 0건", file=sys.stderr)
    for item in (report["errors"] + report["warnings"])[:20]:
        label = f"{item['row']}번째 장병 ({item['soldier_id']})" if item["row"] else "입력 파일"
        print(f"- {label} / {item['field']}: {item['message']}")
    if summary["error_count"] + summary["warning_count"] > 20:
        print("- 나머지 오류·경고는 결과 JSON에서 확인하세요.")
    print(f"결과: {args.output.resolve()}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
