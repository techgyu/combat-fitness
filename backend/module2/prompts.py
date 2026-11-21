"""계획 생성·수정용 프롬프트.

규칙 값은 데이터 팩에서 읽어 넣으며, 프롬프트 문장에 직접 적지 않음.
"""
from __future__ import annotations

import json
from typing import Any

from .catalog import Catalog
from .models import PlanInput, Violation

_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_NULLABLE_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}

PLAN_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "week": {"type": "integer"},
                    "exercise_id": {"type": "string"},
                    "sessions_per_week": {"type": "integer"},
                    "sets": _NULLABLE_INT,
                    "reps": _NULLABLE_INT,
                    "seconds": _NULLABLE_INT,
                    "minutes": _NULLABLE_INT,
                    "load_kg": _NULLABLE_NUM,
                    "targets": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["week", "exercise_id", "sessions_per_week", "sets", "reps", "seconds",
                             "minutes", "load_kg", "targets", "reason", "evidence_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "rows"],
    "additionalProperties": False,
}


def _catalog_for_prompt(catalog: Catalog) -> list[dict[str, Any]]:
    keys = ("exercise_id", "name", "category", "related_tests", "difficulty", "equipment",
            "dose", "frequency_per_week", "restrictions", "evidence_ids")
    excluded = set(catalog.rules["excluded_exercises"]["value"])
    return [{k: ex[k] for k in keys} for ex in catalog.exercises.values() if ex["exercise_id"] not in excluded]


def build_system_prompt(catalog: Catalog) -> str:
    r = catalog.rules
    diff_rules = "; ".join(
        f"{d['weeks'][0]}~{d['weeks'][1]}주차 난이도 {d['max_difficulty']} 이하" for d in r["difficulty_by_week"]["rules"]
    )
    excluded = r["excluded_exercises"]["value"]
    cap = r["rep_cap_by_record"]
    rec = r["recovery_per_week"]
    rq = r["run_quality"]
    cov = r["coverage"]
    prog = r["weekly_progression"]
    caps = r["weekly_caps"]
    expl = r["explanation"]
    return f"""당신은 보병 소총수의 체력단련 계획을 작성하는 코치입니다. 모든 장병 데이터는 합성 데이터입니다.

# 목적
연령별 체력검정 각 종목(2분 팔굽혀펴기, 2분 윗몸일으키기, 3km 달리기)의 1급 이상 달성을 목표로 하면서,
15kg 군장 훈련 수행에 필요한 체력을 준비하는 {r['plan_weeks']['value']}주 운동 계획을 작성합니다.

# 입력 해석
- 차이값(Δ = 목표 − 현재)은 이미 계산되어 전달됩니다. 다시 계산하거나 바꾸지 마세요.
- 팔굽혀펴기·윗몸일으키기: 양수 Δ는 늘려야 하는 횟수입니다. 3km 달리기: 음수 Δ의 절댓값은 줄여야 하는 초입니다. 0은 이미 목표를 충족했다는 뜻입니다.
- 횟수와 초는 단위가 다르므로 숫자 크기를 비교해 우선순위를 정하지 마세요.
- 하중비는 참고 정보일 뿐입니다. 하중비로 목표, 운동량, 우선순위를 정하거나 수행능력을 평가하지 마세요.

# 계획 작성 규칙 (코드가 모두 검증합니다)
1. 아래 운동 목록의 exercise_id만 사용합니다. 목록은 후보이며, 이 장병에게 맞는 운동만 고릅니다. {', '.join(excluded)}는 현재 규칙에서 제외되어 목록에 없으며 사용하지 않습니다.
2. 1~{r['plan_weeks']['value']}주 모두 운동을 배치하고, 주당 운동 수는 {r['exercises_per_week']['min']}~{r['exercises_per_week']['max']}개입니다. 같은 주에 같은 운동을 두 번 넣지 않습니다.
3. sessions_per_week는 해당 운동의 frequency_per_week 범위 안이어야 합니다.
4. 처방값은 해당 운동의 dose.type에 맞는 필드만 채우고 나머지는 null로 둡니다.
   - reps: sets, reps / time: sets, seconds / duration: minutes / ruck: minutes, load_kg
   각 값은 dose의 [최소, 최대] 범위 안이어야 합니다.
5. 주간 총량: 총 세트(Σ sessions_per_week × sets, reps·time 운동)는 {caps['max_total_sets']} 이하, 총 시간(Σ sessions_per_week × minutes, duration·ruck 운동)은 {caps['max_total_minutes']}분 이하입니다. recovery 분류 운동은 총량에 넣지 않습니다.
6. 주간 증가: 각 총량은 전주 대비 ×{prog['max_increase_ratio']} 또는 전주 + {prog['min_allowance_sets']}세트 / + {prog['min_allowance_minutes']}분 중 큰 값을 넘지 않습니다. 감소는 허용됩니다.
7. 난이도: {diff_rules}. 운동별 restrictions.min_week 이전에는 넣지 않습니다.
8. {', '.join(cap['exercise_to_record'])}의 1세트 reps는 요청에 주어진 rep_caps 값 이하입니다(현재 기록 대비 상한). 목표 횟수를 한 세트에 채우려 하지 말고 세트를 나눠 구성합니다.
8-1. 매주 {rec['category']} 분류 운동을 {rec['min_exercises']}개 이상 넣습니다.
8-2. 3km 달리기 개선이 필요하면 {rq['from_week']}주차부터 매주 고강도 달리기({', '.join(rq['exercise_ids'])}) 중 {rq['min_per_week']}개 이상을 넣습니다. 편한 지속주만으로 채우지 않고, 지속주 시간도 주차에 따라 점진적으로 늘립니다.
8-3. {cov['load_adaptation_category']} 분류 운동(들고 걷기, 계단 오르기 등)을 최소 {cov['min_weeks_with_load_adaptation']}개 주에 넣어 15kg 군장 준비를 다룹니다.
8-4. {'마지막 주의 총 세트와 총 시간은 직전 주보다 많지 않게 하여 체력검정 전에 부담을 줄입니다.' if r['final_week_taper']['enabled'] else ''}
9. Δ가 0이 아닌 종목은 매주 그 종목을 targets에 포함한 운동이 1개 이상 있어야 합니다. load_carriage(군장 준비)는 최소 {r['coverage']['min_weeks_with_load_carriage']}개 주에서 다룹니다.
10. targets는 해당 운동의 related_tests 중에서, evidence_ids는 해당 운동의 evidence_ids 중에서만 고릅니다. 둘 다 비워 두지 않습니다.

# 설명 작성 규칙
- reason(행별 추천 이유)과 summary는 한국어로 짧게 씁니다. reason은 1~2문장입니다.
- 같은 운동이 여러 주에 나오면 주차마다 다르게 씁니다. 그 주에 무엇이 바뀌는지(세트·시간 증가, 강도 전환, 유지, 강도 조절 등)와 그 이유를 적고, 숫자만 바꾼 같은 문장을 반복하지 않습니다.
- 장병이 읽는 문장이므로 쉬운 말로 씁니다. 시험은 "체력검정"이라고 부르고, 규칙·시스템 용어({', '.join(expl['discouraged_terms'])})는 쓰지 않습니다.
- 세트와 횟수는 "4세트 28회"처럼 쓰고, 주당 실시 횟수는 "주 2회"처럼 씁니다. "세트 4회"라고 쓰지 않습니다. 반복 횟수의 단위는 "개"가 아니라 "회"로 통일합니다.
- "목표까지 16회 차이가 있습니다" 같은 같은 꼬리 문장을 여러 주에 반복해 붙이지 않습니다. 현재·목표 기록과 차이값은 그 운동이 처음 나오는 주에 한 번 쓰고, 이후 주에는 그 주의 변화와 이유만 씁니다.
- reason에는 그 행의 운동 이야기만 씁니다. 다른 운동이 있거나 없다는 설명은 넣지 않습니다.
- 운동 목록의 restrictions.notes를 따릅니다(예: 동적 스트레칭은 운동 전 준비운동, 정적 스트레칭·폼롤러는 운동 후 정리운동).
- 덤벨·케틀벨을 쓰는 운동은 무게를 숫자 없이 말로 안내합니다(예: "마지막 세트까지 자세를 지킬 수 있는 무게").
- reason에 쓰는 숫자는 전달된 차이값·현재/목표 기록·장병 정보·하중 정보, 그리고 그 행의 주차·처방값만 사용합니다. 다른 주차나 다른 운동의 숫자, 직접 계산한 숫자(백분율, 증가폭 등)는 쓰지 않습니다.
- 3km 달리기 시간은 전달된 초 단위 그대로 씁니다(분:초로 바꾸지 않음).
- 하중비를 언급할 때는 "하중비 X는 참고 정보입니다"처럼 참고 정보로만 씁니다. 같은 문장에 {', '.join(expl['load_ratio_misuse_terms'])} 같은 평가 표현을 쓰지 않습니다.
- 의료 표현({', '.join(expl['forbidden_terms'])})을 쓰지 않습니다.

# 운동 목록 (exercises v{catalog.versions['exercise_catalog']})
{json.dumps(_catalog_for_prompt(catalog), ensure_ascii=False)}

# 출력
지정된 JSON 스키마로 summary와 rows만 출력합니다.
"""


def build_initial_message(plan_input: PlanInput, catalog: Catalog) -> str:
    from .validator import rep_caps

    p = plan_input.payload
    needs = [
        {"column": n.column, "delta": n.delta, "unit": n.unit, "direction": n.direction, "amount": n.amount}
        for n in plan_input.needs
    ]
    data = {
        "soldier": p.soldier.model_dump(),
        "current_records": p.current_records.model_dump(),
        "goal_records": p.goal_records.model_dump(),
        "difference_matrix": {"column_order": p.column_order, "values": p.difference_matrix[0]},
        "needs": needs,
        "load_context": p.load_context.model_dump(),
        "rep_caps": rep_caps(plan_input, catalog),
    }
    return "다음 장병의 8주 운동 계획을 작성하세요.\n" + json.dumps(data, ensure_ascii=False, indent=1)


def build_revision_message(violations: list[Violation], revision_no: int, max_revisions: int) -> str:
    items = [v.model_dump(exclude_none=True) for v in violations]
    return (
        f"코드 검증에서 위반 {len(violations)}건이 나왔습니다 (수정 {revision_no}/{max_revisions}회차).\n"
        "각 위반의 week, exercise_id, field, allowed, actual, reason을 확인하고 모두 고친 전체 계획을 다시 출력하세요. "
        "위반이 없는 부분은 그대로 유지합니다.\n"
        + json.dumps(items, ensure_ascii=False, indent=1)
    )
