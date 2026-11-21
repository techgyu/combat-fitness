#!/usr/bin/env python3
"""Generate synthetic male riflemen for a smoke test (Python 3.10+).

Run from the repository root:
    python backend/module1/02_generate_synthetic_soldiers.py --count 1000 --seed 42

Outputs go beside this script in data/, regardless of the working directory.
Charts require Matplotlib and are saved in data/plots/. Use --plots-only for
existing records, or --no-plots to generate data using the standard library only.
Age counts use verified 2024 MMA tables; body means use Size Korea 2020-2021.
Grouped-age allocation, body spreads/dependence and fitness values are DEMO
ASSUMPTIONS, not measured soldier population distributions. See metadata.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

VERSION = "0.5.0"
MIN_AGE, MAX_AGE = 18, 29
AGE_BASIS = "calendar_year_minus_birth_year"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data"

# MMA 2024 Statistical Yearbook, table 2-1-5, printed p.125.
CONSCRIPT_COUNTS = {
    "19": 5824, "20": 50046, "21": 16251, "22": 4696,
    "23": 2321, "24": 1445, "25+": 2810,
}
# Table 2-3-3, printed p.141: all services, not infantry-only.
VOLUNTEER_COUNTS = {"18": 559, "19": 17080, "20-22": 78060, "23+": 6774}
REFERENCE_TOTAL = 185866

# Only these MEANS were verified in the official Size Korea report.
# Printed p.222: height; p.226: BMI. These are civilian survey age groups.
BODY_MEANS = {
    "20-24": {"height_cm": 174.6, "bmi": 23.8},
    "25-29": {"height_cm": 174.1, "bmi": 24.3},
}
# Deliberate demo assumptions; these are NOT official SDs or eligibility limits.
BODY_ASSUMPTIONS = {
    "height_sd_cm": 5.5,
    "bmi_sd": 3.5,
    "height_bounds_cm": [145.0, 205.0],
    "latent_bmi_bounds": [15.0, 40.0],
    "height_distribution": "truncated_normal",
    "latent_bmi_distribution": "truncated_lognormal",
    "height_latent_bmi_dependence": "independent_within_age_group",
    "age_18_19_profile": "20-24_proxy",
}
# Equal-probability TEST SCENARIOS, independent of body and age.
# Means: pushups per 120 seconds, situps per 120 seconds, unloaded 3km seconds.
FITNESS_SCENARIOS = {
    "balanced_low": (35, 45, 1350),
    "balanced_mid": (55, 65, 960),
    "balanced_high": (76, 90, 780),
    "upper_body_gap": (35, 85, 800),
    "situp_gap": (70, 45, 800),
    "aerobic_gap": (70, 85, 1200),
}
FITNESS_ASSUMPTIONS = {
    "scenario_weights": "equal",
    "standard_deviations": [8, 8, 45],
    "bounds": [[0, 120], [0, 140], [600, 1800]],
    "test_duration_seconds": {"pushups": 120, "situps": 120},
    "run_distance_m": 3000,
    "baseline_test_load_kg": 0,
}

SOURCES = [
    {
        "id": "mma_2024",
        "title": "2024 병무통계연보",
        "url": "https://mma.go.kr/download/ebook/2024_bmtgyb_1.pdf",
        "tables": ["2-1-5 (printed p.125)", "2-3-3 (printed p.141)"],
        "population": "현역 징집병 및 전 군 모집병 입영자",
        "reference_date": "2024-12-31",
    },
    {
        "id": "mma_age",
        "title": "병무청: 2008년생의 빠른 입영방법",
        "url": "https://www.mma.go.kr/board/boardView.do?gesipan_id=317&gsgeul_no=1501415&mc=mma0002306",
        "note": "모집병은 병역법상 연나이 18세부터 지원 가능; 만 나이와 구분",
    },
    {
        "id": "sizekorea_2021",
        "title": "한국인인체치수조사 통계정보보고서 (2021.12, 작성 2022.10.11)",
        "url": "https://mods.go.kr/boardDownload.es?bid=12030&list_no=422680&seq=1",
        "pages": ["printed p.222 (height)", "printed p.226 (BMI)"],
        "population": "2020-2021년 민간 남성 인체치수 조사",
    },
]
LIMITATIONS = [
    "실제 개인을 복제한 자료가 아닌 시제품 테스트 데이터이다.",
    "2024년 입영자 분포를 현재 복무 중인 보병 소총수의 연령 분포에 대용한다.",
    "2025년 자료의 존재는 확인했으나 이 버전은 수치를 확인한 2024년 자료에 고정한다.",
    "병역법상 연나이를 사용한다. 생일을 기준으로 계산한 만 나이가 아니다.",
    "모집병 20-22세는 20/21/22세에 균등 배분한다.",
    "모집병 23세 이상과 징집병 25세 이상은 각각 23-29세, 25-29세로 균등 배분한다.",
    "30세 이상 인원을 따로 분리할 수 없어 상한 29세 안에 배분했다. 18-29세 모집단의 정확한 조건부 분포가 아니다.",
    "20대 신체 평균의 연령 구간에 연나이를 직접 대응한 것은 시연용 근사이다.",
    "18-19세 신체 평균은 20-24세 값을 대용한다. 해당 연령의 실측값을 확보한 것이 아니다.",
    "키/BMI의 표준편차, 분포 형태, 절단 범위, 독립 가정은 미검증 시연용 설정이다.",
    "키와 잠재 BMI를 생성한 뒤 체중을 계산한다. 최종 BMI는 저장된 키/체중으로 다시 계산한다.",
    "이 방식이 만드는 키-체중 관계는 모델 가정이며 실측 상관관계를 재현했다고 주장하지 않는다.",
    "절단과 반올림으로 생성 표본의 평균은 원래 평균과 달라질 수 있다.",
    "체력 시나리오/운동 기록은 임의의 테스트 규칙이다. 신체치수에서 체력을 예측하지 않는다.",
    "15kg과 하중비는 군장 훈련 준비의 참고 조건이다. 체력 기록은 무군장 합성 기록이다.",
    "2분 기록은 새 시연용 시나리오로 생성하며, 이전 1분 기록을 환산한 값이 아니다.",
    "생성 범위는 입영 판정 기준이나 실제 운동 처방의 안전 기준을 뜻하지 않는다.",
]


def age_weights() -> dict[int, float]:
    """Keep single-year observations; split only the published grouped counts."""
    weights = {age: 0.0 for age in range(MIN_AGE, MAX_AGE + 1)}
    for label, count in CONSCRIPT_COUNTS.items():
        if label == "25+":
            for age in range(25, MAX_AGE + 1):
                weights[age] += count / (MAX_AGE - 24)
        else:
            weights[int(label)] += count
    weights[18] += VOLUNTEER_COUNTS["18"]
    weights[19] += VOLUNTEER_COUNTS["19"]
    for age in range(20, 23):
        weights[age] += VOLUNTEER_COUNTS["20-22"] / 3
    for age in range(23, MAX_AGE + 1):
        weights[age] += VOLUNTEER_COUNTS["23+"] / (MAX_AGE - 22)
    if not math.isclose(sum(weights.values()), REFERENCE_TOTAL):
        raise ValueError("Reference age counts do not sum to 185866.")
    return weights


def bounded_sample(draw, lower: float, upper: float) -> float:
    # Reject, rather than clip, to avoid artificial piles at the bounds.
    for _ in range(10000):
        value = draw()
        if math.isfinite(value) and lower <= value <= upper:
            return value
    raise ValueError("Could not sample within bounds; check distribution settings.")


def generate_body(rng: random.Random, age: int) -> tuple[float, float, float, str]:
    group = "20-24" if age < 25 else "25-29"
    means = BODY_MEANS[group]
    height = round(bounded_sample(
        lambda: rng.gauss(means["height_cm"], BODY_ASSUMPTIONS["height_sd_cm"]),
        *BODY_ASSUMPTIONS["height_bounds_cm"],
    ), 1)
    # Convert arithmetic mean/SD to the lognormal parameters.
    variance_log = math.log1p((BODY_ASSUMPTIONS["bmi_sd"] / means["bmi"]) ** 2)
    mean_log = math.log(means["bmi"]) - variance_log / 2
    latent_bmi = bounded_sample(
        lambda: rng.lognormvariate(mean_log, math.sqrt(variance_log)),
        *BODY_ASSUMPTIONS["latent_bmi_bounds"],
    )
    weight = round(latent_bmi * (height / 100) ** 2, 1)
    bmi = round(weight / (height / 100) ** 2, 2)
    profile = "18-19_using_20-24_proxy" if age < 20 else group
    return height, weight, bmi, profile


def generate_records(count: int = 1000, seed: int = 42, service_year: int = 2026) -> list[dict]:
    if type(service_year) is not int or not 2000 <= service_year <= 2099:
        raise ValueError("service_year must be a four-digit year from 2000 to 2099.")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000:
        raise ValueError("count must be an integer between 1 and 100000.")
    rng = random.Random(seed)
    weights = age_weights()
    ages = list(weights)
    records = []
    for index in range(1, count + 1):
        age = rng.choices(ages, weights=list(weights.values()), k=1)[0]
        height, weight, bmi, body_profile = generate_body(rng, age)
        scenario = rng.choice(list(FITNESS_SCENARIOS))
        fitness = [
            int(round(bounded_sample(
                lambda mean=mean, sd=sd: rng.gauss(mean, sd), *bounds,
            )))
            for mean, sd, bounds in zip(
                FITNESS_SCENARIOS[scenario],
                FITNESS_ASSUMPTIONS["standard_deviations"],
                FITNESS_ASSUMPTIONS["bounds"],
            )
        ]
        records.append({
            "soldier_id": f"{service_year % 100:02d}-{index:08d}",
            "is_synthetic": True,
            "age": age,
            "age_basis": AGE_BASIS,
            "sex": "male",
            "role": "infantry_rifleman",
            "height_cm": height,
            "weight_kg": weight,
            "bmi": bmi,
            "combat_load_kg": 15.0,
            "record_schema_version": "2.0",
            "pushups_duration_seconds": 120,
            "situps_duration_seconds": 120,
            "run_distance_m": 3000,
            "baseline_test_load_kg": 0,
            "pushups_2min": fitness[0],
            "situps_2min": fitness[1],
            "run_3km_seconds": fitness[2],
            "body_reference_group": body_profile,
            "fitness_scenario": scenario,
        })
    return records


def make_metadata(records: list[dict], seed: int) -> dict:
    weights = age_weights()
    distribution = Counter(row["age"] for row in records)
    numerical = ["height_cm", "weight_kg", "bmi", "pushups_2min",
                 "situps_2min", "run_3km_seconds"]
    return {
        "schema_version": VERSION,
        "generator": Path(__file__).name,
        "population_label": "synthetic_riflemen_demo",
        "calibration_status": "official_age_bins_and_body_means_plus_demo_assumptions",
        "count": len(records),
        "seed": seed,
        "soldier_id_format": "YY-NNNNNNNN",
        "service_number_year_prefixes": sorted({r["soldier_id"].split("-")[0] for r in records}),
        "service_number_note": "Synthetic unique lookup keys, not real military service numbers or enlistment histories.",
        "python_version": sys.version.split()[0],
        "age_range": [MIN_AGE, MAX_AGE],
        "age_basis": AGE_BASIS,
        "age_reference_year": 2024,
        "official_conscript_counts": CONSCRIPT_COUNTS,
        "official_volunteer_counts": VOLUNTEER_COUNTS,
        "reference_total": REFERENCE_TOTAL,
        "model_age_probabilities": {
            str(age): weight / REFERENCE_TOTAL for age, weight in weights.items()
        },
        "generated_age_counts": {str(age): distribution[age] for age in weights},
        "generated_fraction_18_to_23": sum(
            distribution[age] for age in range(18, 24)
        ) / len(records),
        "body_verified_means": BODY_MEANS,
        "body_assumptions": BODY_ASSUMPTIONS,
        "fitness_scenario_means": FITNESS_SCENARIOS,
        "fitness_assumptions": FITNESS_ASSUMPTIONS,
        "generated_summary": {
            field: {
                "mean": round(statistics.mean(row[field] for row in records), 4),
                "population_sd": round(statistics.pstdev(row[field] for row in records), 4),
                "min": min(row[field] for row in records),
                "max": max(row[field] for row in records),
            } for field in numerical
        },
        "sources": SOURCES,
        "limitations_and_assumptions": LIMITATIONS,
    }


def percentile(sorted_values: list[float], probability: float) -> float:
    """Linear interpolation at index (n-1)*p; also valid for one observation."""
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def statistics_tables(records: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    count = len(records)
    units = {
        "age": "calendar_year_age", "height_cm": "cm", "weight_kg": "kg",
        "bmi": "kg/m^2", "pushups_2min": "repetitions/120s",
        "situps_2min": "repetitions/120s", "run_3km_seconds": "seconds",
        "combat_load_kg": "kg",
    }
    summary = []
    for field, unit in units.items():
        values = sorted(row[field] for row in records)
        summary.append({
            "field": field, "unit": unit, "count": count,
            "mean": round(statistics.mean(values), 4),
            "std_population": round(statistics.pstdev(values), 4),
            "min": values[0],
            "p05": round(percentile(values, 0.05), 4),
            "p25": round(percentile(values, 0.25), 4),
            "median": round(statistics.median(values), 4),
            "p75": round(percentile(values, 0.75), 4),
            "p95": round(percentile(values, 0.95), 4),
            "max": values[-1],
        })
    age_counts = Counter(row["age"] for row in records)
    age_table = [{
        "age": age, "age_basis": AGE_BASIS,
        "count": age_counts[age],
        "actual_percent": round(age_counts[age] / count * 100, 4),
        "model_expected_percent": round(weight / REFERENCE_TOTAL * 100, 4),
        "model_expected_count": round(weight / REFERENCE_TOTAL * count, 4),
    } for age, weight in age_weights().items()]
    scenario_counts = Counter(row["fitness_scenario"] for row in records)
    fitness_table = [{
        "fitness_scenario": name, "count": scenario_counts[name],
        "actual_percent": round(scenario_counts[name] / count * 100, 4),
        "model_expected_percent": round(100 / len(FITNESS_SCENARIOS), 4),
        "basis": "demo_scenario_equal_probability",
    } for name in FITNESS_SCENARIOS]
    return summary, age_table, fitness_table


def write_outputs(records: list[dict], seed: int, output_dir: Path,
                  overwrite: bool = False) -> list[Path]:
    paths = [output_dir / name for name in (
        "synthetic_soldiers.csv", "synthetic_soldiers.json", "generation_metadata.json",
        "summary_statistics.csv", "age_distribution.csv", "fitness_distribution.csv",
    )]
    if not overwrite:
        existing = [str(path) for path in paths if path.exists()]
        if existing:
            raise FileExistsError(
                "Output already exists; use --overwrite or --output-dir: " + ", ".join(existing)
            )
    metadata = make_metadata(records, seed)
    summary, age_table, fitness_table = statistics_tables(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    # UTF-8 BOM allows Korean Windows Excel to read CSV without mojibake.
    for path, rows in (
        (paths[0], records), (paths[3], summary),
        (paths[4], age_table), (paths[5], fitness_table),
    ):
        with path.open(mode, encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    for path, value in ((paths[1], records), (paths[2], metadata)):
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    return paths


# Matplotlib is loaded lazily so --no-plots can still use the stdlib alone.
plt = None


def load_plotting():
    global plt
    if plt is None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise RuntimeError(
                "Matplotlib is required for charts. Run: python -m pip install matplotlib "
                "(or generate tables only with --no-plots)."
            ) from exc
    return plt


PLOT_NAMES = (
    "01_age_distribution.png",
    "02_body_distributions.png",
    "03_fitness_distributions.png",
    "04_height_weight.png",
    "05_fitness_scenarios.png",
    "06_summary_table.png",
)
REQUIRED_NUMBERS = (
    "age", "height_cm", "weight_kg", "bmi",
    "pushups_2min", "situps_2min", "run_3km_seconds", "combat_load_kg",
)
BODY_METRICS = (
    ("height_cm", "Height (cm)", 1.0),
    ("weight_kg", "Weight (kg)", 1.0),
    ("bmi", "BMI (kg/m2)", 1.0),
)
FITNESS_METRICS = (
    ("pushups_2min", "Push-ups (reps / 120 s)", 1.0),
    ("situps_2min", "Sit-ups (reps / 120 s)", 1.0),
    ("run_3km_seconds", "3 km run (minutes)", 1 / 60),
)
COLORS = ("#2563eb", "#0891b2", "#7c3aed")
STYLE = {
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "axes.grid": True,
    "grid.alpha": 0.18,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
}


def check_plot_targets(output_dir: Path, overwrite: bool = False) -> list[Path]:
    paths = [output_dir / "plots" / name for name in PLOT_NAMES]
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Charts already exist; use --overwrite or another --output-dir: "
            + ", ".join(existing)
        )
    return paths


def validate_records(records: list[dict]) -> None:
    if not isinstance(records, list) or not records:
        raise ValueError("synthetic_soldiers.json must contain a non-empty array.")
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Record {index} must be an object.")
        for key in REQUIRED_NUMBERS:
            value = row.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"Record {index}: {key} must be a finite number.")
        if not 18 <= row["age"] <= 29 or int(row["age"]) != row["age"]:
            raise ValueError(f"Record {index}: age must be an integer in 18..29.")
        if any(row[key] <= 0 for key in ("height_cm", "weight_kg", "bmi", "run_3km_seconds")):
            raise ValueError(f"Record {index}: body measurements and run time must be positive.")
        if any(row[key] < 0 for key in ("pushups_2min", "situps_2min", "combat_load_kg")):
            raise ValueError(f"Record {index}: counts and load cannot be negative.")
        if not isinstance(row.get("fitness_scenario"), str) or not row["fitness_scenario"]:
            raise ValueError(f"Record {index}: fitness_scenario is required.")


def expected_age_percent(metadata: dict) -> list[float] | None:
    probabilities = metadata.get("model_age_probabilities")
    if probabilities is None:
        return None
    if not isinstance(probabilities, dict):
        raise ValueError("Invalid model_age_probabilities in generation_metadata.json.")
    values = [probabilities.get(str(age)) for age in range(18, 30)]
    if any(isinstance(p, bool) or not isinstance(p, (int, float))
           or not math.isfinite(p) or p < 0 for p in values):
        raise ValueError("Expected age probabilities must cover ages 18..29.")
    if not math.isclose(sum(values), 1.0, abs_tol=1e-6):
        raise ValueError("Expected age probabilities must sum to one.")
    return [p * 100 for p in values]


def save_figure(fig, path: Path, title: str, count: int, note: str = "") -> None:
    fig.suptitle(f"{title}  |  N = {count:,}", fontsize=16, fontweight="bold", y=0.99)
    footer = "Synthetic test data; generation assumptions apply."
    if note:
        footer += "  " + note
    fig.text(0.02, 0.015, footer, fontsize=8, color="#64748b")
    try:
        fig.tight_layout(rect=(0, 0.07, 1, 0.93))
        fig.savefig(path, dpi=180, bbox_inches="tight")
    finally:
        plt.close(fig)


def histogram_figure(records: list[dict], metrics):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    bins = min(30, max(1, round(math.sqrt(len(records)))))
    for ax, (key, label, scale), color in zip(axes, metrics, COLORS):
        values = [row[key] * scale for row in records]
        mean, median = statistics.mean(values), statistics.median(values)
        ax.hist(values, bins=bins, color=color, edgecolor="white", alpha=0.85)
        ax.axvline(mean, color="#ea580c", linewidth=2, label=f"Mean: {mean:.2f}")
        ax.axvline(median, color="#334155", linestyle="--", label=f"Median: {median:.2f}")
        ax.set(xlabel=label, ylabel="Count", title=label)
        ax.legend(fontsize=9)
        ax.text(
            0.97, 0.78, f"SD: {statistics.pstdev(values):.2f}",
            transform=ax.transAxes, ha="right", fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"},
        )
    return fig


def write_plots(records: list[dict], metadata: dict, output_dir: Path,
                overwrite: bool = False) -> list[Path]:
    load_plotting()
    validate_records(records)
    if not isinstance(metadata, dict):
        raise ValueError("generation_metadata.json must be an object.")
    if "count" in metadata and metadata["count"] != len(records):
        raise ValueError("Record count differs from generation_metadata.json.")
    expected = expected_age_percent(metadata)
    paths = check_plot_targets(output_dir, overwrite)
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    count = len(records)
    with plt.rc_context(STYLE):
        # 1. Ages: observed sample vs. the stored generator model, not raw official ratios.
        fig, ax = plt.subplots(figsize=(12, 5.5))
        ages = list(range(18, 30))
        counts = Counter(row["age"] for row in records)
        bars = ax.bar(ages, [counts[a] / count * 100 for a in ages],
                      color=COLORS[0], label="Generated sample")
        for bar, age in zip(bars, ages):
            ax.annotate(f"{counts[age]:,}", (bar.get_x() + bar.get_width() / 2,
                        bar.get_height()), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=9)
        if expected is not None:
            ax.plot(ages, expected, "o--", color="#ea580c", label="Stored model expectation")
        ax.set(xlabel="Age (calendar year minus birth year)", ylabel="Share (%)")
        ax.set_xticks(ages)
        ax.set_ylim(0, max([counts[a] / count * 100 for a in ages] + (expected or [0])) * 1.2)
        ax.legend()
        save_figure(fig, paths[0], "Age distribution", count,
                    "Bar labels: count. Expected ratios include age-bin allocation assumptions."
                    if expected is not None else "Expected ratios unavailable; observed data only.")

        # 2-3. Distribution of physical measurements and fitness records.
        save_figure(histogram_figure(records, BODY_METRICS), paths[1],
                    "Body measurements", count, "SD is the population standard deviation.")
        save_figure(histogram_figure(records, FITNESS_METRICS), paths[2],
                    "Fitness records", count, "Run time converted from seconds to minutes.")

        # 4. Correlation describes this generated sample only.
        heights = [row["height_cm"] for row in records]
        weights = [row["weight_kg"] for row in records]
        r = None
        if count > 1 and statistics.pstdev(heights) > 0 and statistics.pstdev(weights) > 0:
            r = statistics.correlation(heights, weights)
        stride = max(1, math.ceil(count / 10000))
        shown = records[::stride]
        fig, ax = plt.subplots(figsize=(10, 6))
        points = ax.scatter(
            [row["height_cm"] for row in shown], [row["weight_kg"] for row in shown],
            c=[row["bmi"] for row in shown], cmap="viridis",
            s=20, alpha=0.65, edgecolors="none",
        )
        fig.colorbar(points, ax=ax, label="BMI (kg/m2)")
        ax.set(xlabel="Height (cm)", ylabel="Weight (kg)")
        ax.set_title(f"Generated-sample Pearson r = {r:.3f}" if r is not None
                     else "Pearson r unavailable (too few or constant values)")
        save_figure(fig, paths[3], "Height and weight", count,
                    f"Points shown: {len(shown):,}. Association comes from the synthetic model.")

        # 5. Scenario frequencies: a test-case mix, not observed soldier fitness prevalence.
        observed = Counter(row["fitness_scenario"] for row in records)
        stored_scenarios = metadata.get("fitness_scenario_means", {})
        if not isinstance(stored_scenarios, dict):
            stored_scenarios = {}
        names = list(dict.fromkeys([*stored_scenarios, *observed]))
        fig, ax = plt.subplots(figsize=(12, 6))
        positions = list(range(len(names)))
        bars = ax.barh(positions, [observed[name] / count * 100 for name in names],
                       color=COLORS[1])
        ax.set_yticks(positions, [name.replace("_", " ") for name in names])
        ax.invert_yaxis()
        for bar, name in zip(bars, names):
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{observed[name]:,} ({observed[name] / count * 100:.1f}%)",
                    va="center", fontsize=9)
        assumptions = metadata.get("fitness_assumptions", {})
        if (stored_scenarios and isinstance(assumptions, dict)
                and assumptions.get("scenario_weights") == "equal"
                and set(observed) <= set(stored_scenarios)):
            ax.axvline(100 / len(stored_scenarios), color="#ea580c", linestyle="--",
                       label="Stored equal-probability expectation")
            ax.legend(loc="lower right")
        ax.set(xlabel="Share (%)")
        ax.set_xlim(0, max(observed.values()) / count * 100 * 1.35)
        save_figure(fig, paths[4], "Fitness test scenarios", count)

        # 6. A readable numeric table as an image.
        metrics = (("age", "Age (calendar years)", 1.0), *BODY_METRICS,
                   *FITNESS_METRICS, ("combat_load_kg", "Combat load (kg)", 1.0))
        table_rows = []
        for key, label, scale in metrics:
            values = [row[key] * scale for row in records]
            numbers = (statistics.mean(values), statistics.pstdev(values), min(values),
                       percentile(sorted(values), 0.05), statistics.median(values),
                       percentile(sorted(values), 0.95), max(values))
            table_rows.append([label, *[f"{value:.2f}" for value in numbers]])
        fig, ax = plt.subplots(figsize=(15, 5.5))
        ax.axis("off")
        table = ax.table(
            cellText=table_rows,
            colLabels=["Metric", "Mean", "SD", "Min", "P05", "Median", "P95", "Max"],
            colWidths=[0.28] + [0.102] * 7, cellLoc="center", loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.8)
        for (row, column), cell in table.get_celld().items():
            cell.set_edgecolor("#e2e8f0")
            if row == 0:
                cell.set_facecolor("#1e3a8a")
                cell.set_text_props(color="white", weight="bold")
            else:
                cell.set_facecolor("#eff6ff" if row % 2 else "white")
            if column == 0 and row > 0:
                cell.set_text_props(ha="left")
        save_figure(fig, paths[5], "Summary statistics", count,
                    "SD: population SD. Run time: minutes. Percentiles: linear interpolation.")
    return paths


def self_test() -> None:
    """Behavior checks; the PNG export test runs when Matplotlib is installed."""
    import tempfile
    import unittest

    class GeneratorTests(unittest.TestCase):
        def test_reference_counts_and_age_bins(self):
            self.assertEqual(sum(CONSCRIPT_COUNTS.values()), 83393)
            self.assertEqual(sum(VOLUNTEER_COUNTS.values()), 102473)
            weights = age_weights()
            self.assertAlmostEqual(sum(weights.values()), 185866)
            self.assertAlmostEqual(sum(weights[a] for a in range(20, 23)), 149053)
            self.assertEqual(weights[18], 559)

        def test_repeatability_consistency_and_young_majority(self):
            rows = generate_records(2000, 42)
            self.assertEqual(rows, generate_records(2000, 42))
            self.assertNotEqual(rows, generate_records(2000, 43))
            self.assertEqual(len({row["soldier_id"] for row in rows}), 2000)
            self.assertGreater(sum(18 <= row["age"] <= 23 for row in rows) / 2000, 0.85)
            for row in rows:
                self.assertTrue(18 <= row["age"] <= 29)
                self.assertEqual(row["bmi"], round(
                    row["weight_kg"] / (row["height_cm"] / 100) ** 2, 2
                ))
                self.assertEqual(row["combat_load_kg"], 15.0)
                self.assertTrue(0 <= row["pushups_2min"] <= 120)
                self.assertTrue(0 <= row["situps_2min"] <= 140)
                self.assertTrue(600 <= row["run_3km_seconds"] <= 1800)

        def test_statistics_include_empty_ages_and_single_row(self):
            rows = generate_records(1, 123)
            summary, age_table, fitness_table = statistics_tables(rows)
            self.assertEqual(len(age_table), 12)
            self.assertEqual(sum(row["count"] for row in age_table), 1)
            self.assertEqual(sum(row["count"] for row in fitness_table), 1)
            for entry in summary:
                self.assertEqual(entry["std_population"], 0)
                self.assertEqual(entry["p05"], entry["p95"])
                self.assertEqual(entry["mean"], rows[0][entry["field"]])
            self.assertAlmostEqual(percentile([10, 20, 30, 40], 0.25), 17.5)

        def test_invalid_count_and_export(self):
            for value in (0, -1, 100001, 1.5, True):
                with self.assertRaises(ValueError):
                    generate_records(value)
            with tempfile.TemporaryDirectory() as folder:
                rows = generate_records(3, 17)
                paths = write_outputs(rows, 17, Path(folder))
                self.assertEqual(json.loads(paths[1].read_text(encoding="utf-8")), rows)
                with paths[0].open(encoding="utf-8-sig", newline="") as handle:
                    self.assertEqual(len(list(csv.DictReader(handle))), 3)
                with self.assertRaises(FileExistsError):
                    write_outputs(rows, 17, Path(folder))
                self.assertEqual(len(write_outputs(rows, 17, Path(folder), True)), 6)

        def test_plots_from_existing_single_record_preserve_inputs(self):
            import importlib.util
            if importlib.util.find_spec("matplotlib") is None:
                self.skipTest("Install matplotlib to run the PNG export test.")
            with tempfile.TemporaryDirectory() as folder:
                output_dir = Path(folder)
                data_paths = write_outputs(generate_records(1, 9), 9, output_dir)
                before = {path: path.read_bytes() for path in data_paths}
                rows, metadata = load_existing_data(output_dir)
                charts = write_plots(rows, metadata, output_dir)
                self.assertEqual(len(charts), 6)
                for path in charts:
                    self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(before, {path: path.read_bytes() for path in data_paths})
                with self.assertRaises(FileExistsError):
                    write_plots(rows, metadata, output_dir)

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(GeneratorTests)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)


def load_existing_data(output_dir: Path) -> tuple[list[dict], dict]:
    """Read existing records; never regenerate or rewrite the input files."""
    records_path = output_dir / "synthetic_soldiers.json"
    if not records_path.is_file():
        raise FileNotFoundError(
            f"{records_path} is missing. Generate data first or select --output-dir."
        )
    records = json.loads(records_path.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list) or not records:
        raise ValueError("synthetic_soldiers.json must contain a non-empty array.")
    metadata_path = output_dir / "generation_metadata.json"
    metadata = (json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                if metadata_path.is_file() else {})
    if not isinstance(metadata, dict):
        raise ValueError("generation_metadata.json must be an object.")
    return records, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--service-year", type=int, default=2026)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    plot_mode = parser.add_mutually_exclusive_group()
    plot_mode.add_argument("--plots-only", action="store_true",
                           help="Read existing JSON and save charts only; do not regenerate data.")
    plot_mode.add_argument("--no-plots", action="store_true",
                           help="Generate data/tables without requiring Matplotlib.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    try:
        if not args.no_plots:
            # Check the dependency and existing chart paths BEFORE writing new data.
            load_plotting()
            check_plot_targets(args.output_dir, args.overwrite)
        if args.plots_only:
            rows, metadata = load_existing_data(args.output_dir)
            paths = []
        else:
            rows = generate_records(args.count, args.seed, args.service_year)
            metadata = make_metadata(rows, args.seed)
            paths = write_outputs(rows, args.seed, args.output_dir, args.overwrite)
        if not args.no_plots:
            paths.extend(write_plots(rows, metadata, args.output_dir, args.overwrite))
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    if args.plots_only:
        print(f"Saved charts for {len(rows)} EXISTING records; input files were not changed.")
    else:
        print(f"Generated {len(rows)} synthetic records (seed={args.seed}).")
    print("Body spreads and fitness are DEMO assumptions; see generation_metadata.json.")
    print("Age basis: calendar year minus birth year (not completed age).")
    print("Age counts:", dict(sorted(Counter(row["age"] for row in rows).items())))
    for path in paths:
        print(path.resolve())


if __name__ == "__main__":
    main()
