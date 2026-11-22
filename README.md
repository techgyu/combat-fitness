# 장병 전투체력 관리 시제품

웹에서 합성 장병을 조회하거나 입력하고, 모듈 1이 연령별 1급 목표와 `Goal − Now`를 계산한다. 모듈 2는 현재 체력과 보병 소총수의 15kg 군장 훈련 준비를 고려해 Claude로 8주 보완 운동 계획을 생성·검증한다. 결과와 수정 이력은 웹에 표시하고 SQLite에 보관한다.

## Windows에서 실행

Python 3.11 이상을 사용한다. PowerShell에서 프로젝트 루트(`start_demo.ps1`이 있는 `repository` 또는 `combat-fitness` 폴더)로 이동한다.

```powershell
# 최초 한 번: 프로젝트 전용 .venv에 필요한 패키지 설치, 빈 .env 준비
.\setup.ps1

# 로컬 설정 파일 편집
notepad .env
```

[Claude Console](https://console.anthropic.com/settings/keys)에서 발급한 키를 `.env`에 입력한다. API 호출에는 해당 계정의 API 사용 요금·크레딧이 적용된다.

```dotenv
ANTHROPIC_API_KEY=발급받은_API_키
MODULE2_MODEL=claude-haiku-5-5
MODULE2_EFFORT=medium
```

키는 서버에서만 읽으며 브라우저에 전달하지 않는다. `.env`는 Git에서 제외된다. 운영체제 환경변수가 `.env`보다 우선한다. 설정 변경 후 실행 중인 서버는 재시작한다.

```powershell
.\start_demo.ps1
```

브라우저에서 **http://127.0.0.1:8000**에 접속한다. 웹·모듈 1(8000)과 실제 모듈 2(8001)가 함께 시작되고 `Ctrl+C`로 종료한다. API 키가 없어도 조회·입력·목표 계산은 가능하며, 계획 생성 요청에는 키 설정 안내가 표시된다. 시작만으로 Claude를 호출하지 않는다.

```powershell
# 포트가 이미 사용 중인 경우
.\start_demo.ps1 -Port 8100 -Module2Port 8101

# 접수 통신만 확인하는 기존 모의 서버
.\start_demo.ps1 -MockModule2

# 별도로 실행 중인 모듈 2 연결
.\start_demo.ps1 -Module2Url "http://127.0.0.1:9000"
```

`-Python`으로 실행할 Python을 지정할 수 있다. 기본값은 프로젝트 `.venv`를 우선한다. `-MockPort`는 기존 명령 호환을 위한 `-Module2Port` 별칭이며, 모의 서버를 선택하려면 `-MockModule2`를 명시한다.

## 사용 흐름

1. 군번으로 장병을 조회하거나 ‘새 사례’에서 가상 기록을 저장한다.
2. 현재 기록·1급 목표·부호가 있는 차이와 하중비를 확인한다.
3. **8주 계획 생성**을 누른다. 실제 Claude 호출은 이때만 발생한다.
4. 생성 → 코드 검증 → 필요 시 최대 2회 수정 후 결과가 표시된다. 총 Claude 호출은 최대 3회이며 요청 실패 시 자동 재전송하지 않는다.
5. 주차별 운동·운동량·빈도·보완 대상·추천 이유·근거 ID와 검증 결과·수정 이력을 확인한다. 장병을 다시 조회해도 마지막 생성 결과를 확인할 수 있다.

검정 종목을 단순히 더 반복하도록 지시하는 것이 목적이 아니다. 현재 기록은 부족분 판단 자료이며, 보직과 군장 훈련 준비를 위해 하체·코어·유산소·하중 적응·회복 운동을 함께 고려한다. 운동은 등록된 30종 후보 안에서 선택한다. 보직은 현재 보병 소총수로 고정되어 있으며 여러 보직을 비교하는 기능은 포함하지 않는다.

## 데이터와 군번

- `backend/module1/data/synthetic_soldiers.json`, `.csv`: 재현 가능한 합성 원본 1,000명.
- `backend/module1/data/soldiers.sqlite3`: 웹에서 사용하는 SQLite DB.
- `soldier_id`: **군번** 필드이자 DB 기본 키. 형식은 `YY-NNNNNNNN`.
- 기본 데이터: `26-00000001` ~ `26-00001000`. 가상 식별자이며 실제 입대 이력을 의미하지 않는다.
- 웹 입력 시 `22-00000001` 같은 형식의 군번을 직접 지정한다.
- 처음 서버를 시작할 때만 합성 원본을 일괄 검증하여 DB에 넣는다. 이후 재시작해도 웹 입력과 기존 DB를 유지한다.
- CSV/JSON을 재생성해도 이미 초기화된 DB를 자동으로 교체하지 않는다. 다른 데이터 세트를 쓰려면 서버의 `--db`로 새 DB 파일을 지정한다.
- DB의 `source`는 `synthetic` 또는 `web`. 전송 접수·실패 기록은 `deliveries` 테이블에 보관한다.

## 목표와 계산

| 항목 | 18~25세 | 26~29세 | 측정 조건 |
|---|---:|---:|---|
| 팔굽혀펴기 | 64회 이상 | 62회 이상 | 2분 |
| 윗몸일으키기 | 78회 이상 | 76회 이상 | 2분 |
| 3km 달리기 | 812초 이하 (13:32) | 832초 이하 (13:52) | 무군장 |

출처는 [목표 기준표](backend/module1/config/target_criteria.json)의 국방부 부대관리훈령 별표 31 링크에 고정한다. 두 번째 기준은 공식 26~30세 구간 중 시제품이 지원하는 26~29세에 적용한다. 나이는 기존 합성 모델의 ‘기준연도 − 출생연도’ 정의를 사용한다.

**Goal의 세 체력 기록은 현재 기록과 관계없이 연령별 1급 기준값으로 고정한다.** 현재 기록이 기준보다 좋아도 Goal을 현재 기록으로 바꾸지 않는다. 신장·체중·나이·BMI·성별·보직·하중은 바꾸지 않는다.

- BMI = 체중(kg) / 신장(m)²
- 하중비 = 15 / 체중(kg)
- `Now`, `Goal`, `difference_matrix`는 각각 **1×4**이다.
- 열 순서: 팔굽혀펴기 횟수 / 윗몸일으키기 횟수 / 3km 시간(초) / 하중비
- `difference_matrix = Goal − Now`
- 점수화·정규화·하중 보조지수는 사용하지 않는다.

23세, 75kg, 현재 기록 48회·60회·16분인 경우:

```json
{
  "now_matrix": [[48, 60, 960, 0.2]],
  "goal_matrix": [[64, 78, 812, 0.2]],
  "difference_matrix": [[16, 18, -148, 0]]
}
```

횟수 차이가 양수이면 기준 미달, 음수이면 기준 초과이다. 달리기 차이가 음수이면 단축해야 하는 시간이고, 양수이면 현재 기록이 기준보다 빠른 시간이다. 기준을 넘은 경우에도 차이를 0으로 자르지 않는다. 예를 들어 23세·75kg의 현재 기록이 90회·100회·700초이면 Goal은 64회·78회·812초, 차이는 [-26,-22,112,0]이다. 하중비 차이는 체중과 하중을 유지하므로 항상 0이다. 실제 하중비는 별도 `load_context`에도 전달한다. 이 값으로 군장 수행능력을 점수화하거나 준비 완료를 판정하지 않는다.

## 공유 자료와 API

- 목표 기준: `backend/module1/config/target_criteria.json`
- 운동·근거·계획 규칙 원본: `backend/module2/data/*.json`
- 모듈 1의 `planning_resources.py`가 같은 원본을 기존 API 필드로 변환한다. `module1/config/exercise_catalog.json`, `planning_rules.json`은 문서용 생성 사본이다. 실행 시 원본을 읽으며 이 사본을 직접 수정하지 않는다.
- 웹 → 모듈 1: `POST /api/v1/soldiers`, `POST /api/v1/soldiers/{soldier_id}/module2`
- 모듈 1 → 모듈 2: `GET /health`, `POST /api/v1/plans`
- 실제 응답은 접수 식별자와 `generation_status`, 전체 `result`를 포함한다. `accepted`는 통신 접수이며, 계획 검증 통과는 `result.status == "passed"`로 구분한다.
- [연동 규격](docs/MODULE2_HANDOFF.md), [API 명세](docs/module2.openapi.json), [요청 예시](docs/module2_request.example.json)

기본 실행은 Python 표준 HTTP 서버를 사용한다. FastAPI와 자동 문서가 필요한 경우 같은 서비스를 아래와 같이 실행한다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn module2.api:app --app-dir backend --host 127.0.0.1 --port 9000
.\start_demo.ps1 -Module2Url "http://127.0.0.1:9000"
```

FastAPI의 `/plan`은 모듈 2 단독 실행을 위한 간소화 입력이며, 통합 시스템은 `/api/v1/plans`를 사용한다. 외부 생성 요청을 기다리는 모듈 1 제한시간은 기본 600초, Claude SDK의 대기 제한은 호출당 180초이며 SDK 재시도는 비활성화한다. 서버는 같은 PC에서 사용하는 개발용 루프백 서버다.

## 테스트와 배치

```powershell
# 실제 Claude 호출 없이 단위·HTTP 통합 테스트
.\.venv\Scripts\python.exe -m pytest tests backend/module2/tests -q

# 기존 합성 원본 검증 → 목표 → 차이 JSON 생성
.\.venv\Scripts\python.exe backend/module1/run_module1.py
```

통합 테스트는 임시 DB와 임시 포트를 사용하고 Claude 응답만 대체한다. 실제 API 인증·과금·모델 응답은 사용자 키를 설정한 후 별도 확인한다. 테스트 통과가 실제 훈련 효과를 의미하지 않는다.

운동표의 운동량·빈도 및 보완 대상 매핑은 시제품 가정이다. 개인별 장비와 제한사항은 미수집으로 표시하며, 실제 사용 가능한 장비나 제한 없음으로 확정하지 않는다. 모든 입력은 남성 18~29세 보병 소총수의 합성 사례만 지원한다.
