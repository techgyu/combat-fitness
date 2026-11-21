"""Batch pipeline without an HTTP server."""
import argparse
import sys
from pathlib import Path
from module1_core import ROOT, CONTRACT_VERSION, Module1, load_stage, validator


def run(input_path, output_dir):
    source, directory = Path(input_path).resolve(), Path(output_dir).resolve()
    targets = [directory / "validation_result.json", directory / "module2_input.json"]
    for target in targets:
        if source == target or (source.exists() and target.exists() and source.samefile(target)):
            raise ValueError("입력 파일과 출력 파일은 달라야 합니다.")
    failed = {"contract_version": CONTRACT_VERSION, "status": "failed", "records": []}
    validator.write_report(failed, targets[1])
    engine = Module1()
    report = validator.process_file(source, targets[0])
    if report["status"] != "passed":
        failed["errors"] = report["errors"]
        validator.write_report(failed, targets[1])
        return failed
    result = {"contract_version": CONTRACT_VERSION, "status": "ready", "source": report["source"],
              "records": [engine.from_validated(r) for r in report["records"]],
              "shared_resources": engine.resources}
    validator.write_report(result, targets[1])
    return result


def main():
    parser = argparse.ArgumentParser(description="합성 장병 생성·검증·목표·차이 행렬 저장")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--service-year", type=int, default=2026)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    if args.generate and args.input:
        parser.error("--generate와 --input은 동시에 사용할 수 없습니다.")
    try:
        if args.generate:
            gen = load_stage("02_generate_synthetic_soldiers.py")
            rows = gen.generate_records(args.count, args.seed, args.service_year)
            gen.write_outputs(rows, args.seed, args.output_dir, args.overwrite)
            if args.plots:
                gen.write_plots(rows, gen.make_metadata(rows, args.seed), args.output_dir, args.overwrite)
        result = run(args.input or args.output_dir / "synthetic_soldiers.json", args.output_dir)
        print(f"{result['status']}: {len(result['records'])} records")
        print(args.output_dir / "module2_input.json")
        return 0 if result["status"] == "ready" else 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
