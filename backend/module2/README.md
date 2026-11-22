# 모듈 2: 8주 운동 계획 생성·검증

> 통합 실행은 저장소 루트의 [README](../../README.md)를 따른다. 기본 `start_demo.ps1`이 실제 모듈 2를 `127.0.0.1:8001`에 함께 실행한다. 웹·모듈 1은 `127.0.0.1:8000`이다. 공개 연동 경로는 `/api/v1/plans`이며 `/plan`은 단독 실행용 간소화 입력이다. Goal은 연령별 1급으로 고정하고 기준 초과 기록은 유지 대상으로 처리한다.

모듈 1이 보낸 차이 행렬과 장병 정보를 받아 Claude로 8주 운동 계획을 만들고, 코드로 검증합니다. 위반이 있으면 Claude에 수정을 요청하고 다시 검증합니다(최대 2회).

모든 데이터는 합성 데이터입니다. 검증 통과는 등록된 규칙을 지켰다는 뜻이며, 실제 훈련 효과를 입증하지 않습니다.

## 처리 흐름

1. 모듈 1이 `POST /api/v1/plans`로 계획 생성을 요청한다.
2. `bridge.py`가 연동 규격·공유 자료를 검증하고 내부 입력으로 변환한다.
3. `contract.py`가 열 순서·단위·부호와 `차이 = 목표 − 현재`를 검증한다. 입력 오류는 Claude 호출 없이 `422 input_error`로 반환한다.
4. `llm.py`가 Claude를 호출해 8주 계획을 생성한다.
5. `validator.py`가 7개 항목을 검증한다. 위반 내역이 있으면 Claude에 전달해 최대 2회 수정·재검증한다.
6. `status=accepted`, `generation_status=passed / failed`를 반환한다. `result`에는 계획·검증 결과·수정 이력이 담긴다.

기본 `server.py`와 선택 실행인 FastAPI `api.py`는 같은 `PlanService`를 사용한다. 두 서버 모두 `/api/v1/plans`, `/plan`, `/health`를 제공한다. `/plan`은 `bridge.py` 변환 없이 간소화 입력을 직접 검증하고, 계획 결과를 최상위에 반환한다.

## 설치

프로젝트 루트(`combat-fitness/`)에서 실행합니다. Python 3.11 이상을 사용합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

위 명령은 Linux / macOS용이다. Windows에서는 루트의 `setup.ps1`을 사용한다. 의존성 버전은 루트 `requirements.txt`에서 관리하며 기존 `backend/module2/requirements.txt`는 같은 파일을 참조한다.

## API 키 설정

Claude API 키는 [Claude Console](https://console.anthropic.com)에서 발급합니다. 두 방법 중 하나를 쓰면 되고, 둘 다 있으면 **환경변수로 지정한 키가 우선**합니다. 설정 변경 후 서버를 재시작합니다.

**방법 1. 실행 명령어에 직접 넣기**

```bash
ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python backend/module2/server.py --port 8001
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

아래 명령은 Linux / macOS용이다. Windows의 기본 서버 명령은 `.\.venv\Scripts\python.exe backend/module2/server.py --port 8001`이다. `start_demo.ps1`로 이미 모듈 2를 실행했다면 같은 포트에 중복 실행하지 않는다.

```bash
# 기본 서버 (.env에 키를 넣은 경우)
.venv/bin/python backend/module2/server.py --port 8001

# FastAPI 대체 서버: 기본 서버 대신 선택해서 실행
.venv/bin/python -m uvicorn module2.api:app --app-dir backend --host 127.0.0.1 --port 8001
```

FastAPI 실행 시에만 `http://127.0.0.1:8001/docs`에서 자동 문서를 확인할 수 있다. FastAPI 개발 중에는 `--reload`를 붙이면 코드 수정 시 서버가 자동으로 다시 시작된다.

### 서버 확인

```bash
curl http://127.0.0.1:8001/health
```

응답의 `status`는 `ok`, `service`는 `module2`, `mode`는 `real`, `contract_version`은 `2.0.0`이다. `versions`, `model`, `generation_ready`, `message`도 포함한다. `generation_ready`는 API 키 설정 여부만 확인하며 키의 유효성이나 결제 상태를 검증하지 않는다. 키가 없어도 서버 상태 확인은 가능하다.

### 통합 시스템의 계획 요청: `/api/v1/plans`

모듈 1은 `contract_version`, `request_id`, `module1_result`, `shared_resources`를 전달한다. 필드 규격은 [MODULE2_HANDOFF.md](../../docs/MODULE2_HANDOFF.md)를 따른다. 제공된 요청 예시로 직접 확인할 수도 있다. 아래 POST는 실제 Claude API를 호출하므로 API 키와 크레딧이 필요하다.

```bash
curl -X POST http://127.0.0.1:8001/api/v1/plans \
  -H "Content-Type: application/json" \
  --data-binary @docs/module2_request.example.json
```

### 단독 실행용 계획 요청: `/plan`

```bash
curl -X POST http://127.0.0.1:8001/plan \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": "2.0",
    "operation": "goal_minus_now",
    "column_order": ["pushups_2min", "situps_2min", "run_3km_seconds", "load_to_body_weight_ratio"],
    "column_units": ["reps", "reps", "seconds", "ratio"],
    "difference_matrix": [[16, 18, -148, 0]],
    "improvement_columns": ["pushups_2min", "situps_2min", "run_3km_seconds"],
    "load_context": {"combat_load_kg": 15, "load_to_body_weight_ratio": 0.2, "usage": "reference_only"},
    "soldier": {"soldier_id": "22-00000001", "height_cm": 175, "weight_kg": 75, "bmi": 24.5, "age": 23, "sex": "M", "role": "infantry_rifleman", "synthetic": true},
    "current_records": {"pushups_2min": 48, "situps_2min": 60, "run_3km_seconds": 960},
    "goal_records": {"pushups_2min": 64, "situps_2min": 78, "run_3km_seconds": 812},
    "versions": {"standards": "1.0", "exercise_catalog": "1.0", "plan_rules": "1.0"}
  }'
```

입력 형식은 [PROJECT_SPEC_v3.md](../../docs/module2/PROJECT_SPEC_v3.md)을 따릅니다. FastAPI 서버 실행 중에는 `http://127.0.0.1:8001/docs`에서 직접 요청을 보내 볼 수도 있습니다.

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

`POST /api/v1/plans`는 생성·검증을 마친 후 응답한다. `status: accepted`는 요청 접수 상태이며, 계획 검증 결과는 `generation_status`와 `result.status`로 구분한다.

| 필드 | 내용 |
|---|---|
| `contract_version`, `request_id`, `receipt_id` | 연동 규격 버전, 요청 ID, 모듈 2 접수 ID |
| `status`, `mode` | `accepted`, `real` |
| `generation_status` | 계획의 최종 `passed` 또는 `failed` |
| `plan` | `result.plan`과 같은 운동 행 목록 |
| `result` | 요약·계획·검증 결과·수정 이력을 포함한 전체 결과 |
| `assumptions`, `resources_sha256` | 시제품 가정 및 공유 자료 해시 |

`POST /plan`은 위 `result`에 해당하는 내용을 바로 반환한다. 아래 표의 `status`는 `/plan`의 최상위 필드이며, `/api/v1/plans`의 성공 응답에서는 `result.status`이다. 오류 응답은 두 경로 모두 최상위 `status`와 `error`를 사용한다.

| HTTP | `status` | 의미 |
|---|---|---|
| 200 | `passed` | 검증을 통과한 계획 |
| 200 | `failed` | 수정 한도 초과(`revision_limit_exceeded`) 또는 모델 거부(`model_refusal`). 마지막 계획과 위반 내역 포함 |
| 422 | `input_error` | 입력이 계약과 다름. `error.message`, `error.details`에 사유 |
| 503 | `api_key_missing` / `dependency_missing` | API 키 미설정 / Claude 패키지 미설치 |
| 502 | `llm_auth_error` | API 키가 잘못됨 |
| 502 | `llm_api_error` | Claude API 오류 |
| 503 | `llm_rate_limited` / `llm_unreachable` | 호출 한도 초과 / 연결 실패 |
| 504 | `llm_timeout` | Claude 응답 대기시간 초과. 자동 재전송하지 않음 |

`passed`·`failed` 응답의 주요 필드:

- `soldier`, `records`(현재·목표·차이·개선 필요량), `load_context`(참고 정보)
- `summary`, `plan`(주차별 운동 행: 운동 ID·이름·세트·횟수·추천 이유·근거 ID)
- `validation`(7개 검증 항목별 결과와 위반 내역)
- `history`(시도별 위반 내역), `revisions_used`, `versions`, `notice`(합성 데이터 고지)

## 파일 구성

| 파일 | 역할 |
|---|---|
| `server.py` | 기본 Python HTTP 서버. `POST /api/v1/plans`, `POST /plan`, `GET /health` |
| `api.py` | 같은 경로를 제공하는 FastAPI 대체 서버와 자동 문서 |
| `service.py` | 두 서버의 공통 계획 생성 서비스·오류 응답 |
| `bridge.py` | 모듈 1의 연동 요청을 검증하고 내부 입력 형식으로 변환 |
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
