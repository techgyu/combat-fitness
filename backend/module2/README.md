# 모듈 2: 8주 운동 계획 생성·검증

모듈 1이 보낸 차이 행렬과 장병 정보를 받아 Claude로 8주 운동 계획을 만들고, 코드로 검증합니다. 위반이 있으면 Claude에 수정을 요청하고 다시 검증합니다(최대 2회).

모든 데이터는 합성 데이터입니다. 검증 통과는 등록된 규칙을 지켰다는 뜻이며, 실제 훈련 효과를 입증하지 않습니다.

## 처리 흐름

```
모듈 1 → POST /plan
          │
          ├─ contract.py   입력 계약 검증 (열 순서·단위·부호, Δ = 목표 − 현재)
          │                 실패 → 422 input_error (Claude 호출 안 함)
          │
          ├─ llm.py        Claude가 8주 계획 작성
          ├─ validator.py  코드가 7개 항목 검증
          │                 위반 → 위반 내역을 Claude에 전달 → 수정 → 재검증 (최대 2회)
          │
          └─ 응답: passed / failed + 계획 + 검증 결과 + 수정 이력
```

## 설치

프로젝트 루트(`combat_load_agent/`)에서 실행합니다. Python 3.12가 필요합니다.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/module2/requirements.txt
```

## API 키 설정

Claude API 키는 [Claude Console](https://console.anthropic.com)의 **API 키 → 키 생성**에서 발급합니다. 두 방법 중 하나를 쓰면 되고, 둘 다 있으면 **실행 명령어에 넣은 키가 우선**합니다.

**방법 1. 실행 명령어에 직접 넣기**

```bash
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/uvicorn module2.api:app --app-dir backend --port 8000
```

**방법 2. `.env` 파일에 넣기**

프로젝트 루트에 `.env` 파일을 만들고 아래 한 줄을 넣습니다. `.env`는 `.gitignore`에 들어 있어 GitHub에 올라가지 않습니다.

```
ANTHROPIC_API_KEY=sk-ant-...
```

선택 설정(환경변수 또는 `.env`):

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MODULE2_MODEL` | `claude-haiku-5-5` | 사용할 Claude 모델 |
| `MODULE2_EFFORT` | `medium` | 추론 강도: `low` / `medium` / `high` / `xhigh` / `max` |

## 실행

모든 명령은 프로젝트 루트에서 실행합니다.

### 서버 실행

```bash
# .env에 키를 넣은 경우
.venv/bin/uvicorn module2.api:app --app-dir backend --port 8000

# 키를 명령어에 직접 넣는 경우
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/uvicorn module2.api:app --app-dir backend --port 8000
```

개발 중에는 `--reload`를 붙이면 코드 수정 시 서버가 자동으로 다시 시작됩니다.

### 서버 확인

```bash
curl http://localhost:8000/health
# {"status":"ok","versions":{"exercise_catalog":"1.0","evidence":"1.0","plan_rules":"1.0"}}
```

### 계획 요청

```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "2.0",
    "operation": "goal_minus_now",
    "column_order": ["pushups_2min", "situps_2min", "run_3km_seconds", "load_to_body_weight_ratio"],
    "column_units": ["reps", "reps", "seconds", "ratio"],
    "difference_matrix": [[16, 18, -148, 0]],
    "improvement_columns": ["pushups_2min", "situps_2min", "run_3km_seconds"],
    "load_context": {"combat_load_kg": 15, "load_to_body_weight_ratio": 0.2, "usage": "reference_only"},
    "soldier": {"soldier_id": "SYN-0001", "height_cm": 175, "weight_kg": 75, "bmi": 24.5, "age": 23, "sex": "M", "role": "infantry_rifleman", "synthetic": true},
    "current_records": {"pushups_2min": 48, "situps_2min": 60, "run_3km_seconds": 960},
    "goal_records": {"pushups_2min": 64, "situps_2min": 78, "run_3km_seconds": 812},
    "versions": {"standards": "1.0", "exercise_catalog": "1.0", "plan_rules": "1.0"}
  }'
```

입력 형식은 [PROJECT_SPEC_v3.md 1.6절](../../docs/module2/PROJECT_SPEC_v3.md)을 따릅니다. 서버 실행 중에는 http://localhost:8000/docs 에서 브라우저로 직접 요청을 보내 볼 수도 있습니다.

### 서버 없이 한 번 실행

명세 예시 장병(23세, 48회·60회·960초)으로 루프 전체를 한 번 돌리고 시도별 위반 내역을 출력합니다.

```bash
PYTHONPATH=backend .venv/bin/python -m module2.run_example result.json

# 키를 명령어에 직접 넣는 경우
ANTHROPIC_API_KEY=sk-ant-... PYTHONPATH=backend .venv/bin/python -m module2.run_example result.json
```

한 번 실행에 Claude를 최대 3회(최초 1회 + 수정 2회) 호출하므로 그만큼 API 비용이 듭니다.

### 테스트

가짜 LLM을 쓰므로 API 키 없이 실행되고 비용이 들지 않습니다.

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/module2/tests
```

## 응답

| HTTP | `status` | 의미 |
|---|---|---|
| 200 | `passed` | 검증을 통과한 계획 |
| 200 | `failed` | 수정 한도 초과(`revision_limit_exceeded`) 또는 모델 거부(`model_refusal`). 마지막 계획과 위반 내역 포함 |
| 422 | `input_error` | 모듈 1 입력이 계약과 다름. `errors`에 사유 |
| 502 | `llm_auth_error` | API 키가 잘못됨 |
| 502 | `llm_api_error` | Claude API 오류 |
| 503 | `llm_rate_limited` / `llm_unreachable` | 호출 한도 초과 / 연결 실패 |

`passed`·`failed` 응답의 주요 필드:

- `soldier`, `records`(현재·목표·차이·개선 필요량), `load_context`(참고 정보)
- `summary`, `plan`(주차별 운동 행: 운동 ID·이름·세트·횟수·추천 이유·근거 ID)
- `validation`(7개 검증 항목별 결과와 위반 내역)
- `history`(시도별 위반 내역), `revisions_used`, `versions`, `notice`(합성 데이터 고지)

## 파일 구성

| 파일 | 역할 |
|---|---|
| `api.py` | FastAPI 서버. `POST /plan`, `GET /health` |
| `planner.py` | 생성 → 검증 → 수정 루프. 수정 횟수와 통과 판정은 코드가 결정 |
| `contract.py` | 모듈 1 입력이 API 계약에 맞는지 검증 |
| `validator.py` | 계획 검증 7개 항목 (LLM 없이 동작) |
| `llm.py` | Claude API 호출 (모델 호출은 이 파일에서만) |
| `prompts.py` | 시스템 프롬프트, 최초 요청, 수정 요청 메시지 |
| `catalog.py` | 데이터 팩을 읽고 내부 정합성 확인 |
| `models.py` | 입력·계획·위반 내역 데이터 타입 |
| `run_example.py` | 서버 없이 실제 Claude로 한 번 실행 |
| `data/exercises_v1.0.json` | 운동 30종 (유산소·하체·코어·상체·하중 적응·회복) |
| `data/evidence_v1.0.json` | 근거 문헌 |
| `data/plan_rules_v1.0.json` | 계획 규칙 (주당 운동 수, 주간 상한, 증가율, 제외 운동, 횟수 상한, 회복 운동 등) |
| `tests/` | 단위 테스트 (가짜 LLM 사용) |

검증 기준값은 모두 `data/*.json`에서 읽으며 코드에 적지 않습니다. 기준값을 바꾸려면 JSON만 수정하면 됩니다. 운동 범위·빈도와 계획 규칙은 가안이며 `confirm_needed: true`로 표시되어 있습니다.

## 검증 항목

| 항목 | 내용 |
|---|---|
| 계획 구조 | 1~8주가 모두 있고 각 주에 운동이 있는지 |
| 운동 목록 | 등록된 30종 안에서만 골랐는지 |
| 운동량·빈도 | 운동별 허용 범위, 주당 운동 수(3~6), 주간 상한, 주간 증가율, 마지막 주 총량 ≤ 직전 주, 매주 회복 운동 1개 이상, 팔굽혀펴기·윗몸일으키기 1세트 횟수 ≤ 현재 기록 × 0.6(가안) |
| 적용 조건 | 주차별 난이도, 장비, 제외 운동(배낭 보행 EX27, 바벨 백스쿼트 EX09) 미사용 |
| 추천 근거 | 보완 대상·근거 ID 일치, 개선이 필요한 종목을 매주 다루는지, 3km 개선 필요 시 3주차부터 매주 고강도 달리기, 하중 적응 운동 최소 4개 주 |
| 설명 수치 | 추천 이유의 숫자가 차이값·기록·처방값과 일치하는지, 같은 운동에 숫자만 바꾼 문장을 반복하지 않는지, 어색한 표현("검사 횟수", "허용 범위", "세트 4회" 등)이 없는지 |
| 하중 정보 활용 | 하중비를 점수·가중치로 쓰지 않았는지, 의료 표현이 없는지 |
