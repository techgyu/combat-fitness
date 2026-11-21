# 전투체력 계획 시제품 — 모듈 1

가상 장병의 체력 기록을 검증하고, 연령별 1급 목표 및 원 기록의 차이를 계산한다. 웹 입력과 SQLite 저장, 모듈 2 접수 API 연동까지 포함한다. 모듈 2의 운동 계획 생성·검증은 별도 구현 대상이다.

## 실행

Python 3.10 이상을 사용한다. 웹·DB·API·통신 테스트는 Python 표준 라이브러리만 사용하며, 그래프 생성에만 Matplotlib이 필요하다.

프로젝트 루트(`README.md`가 있는 폴더)에서 PowerShell로 실행한다. GitHub에서 내려받은 경우 폴더 이름은 `combat-fitness`이다.

```powershell
.\start_demo.ps1
```

브라우저에서 **http://127.0.0.1:8000**에 접속한다. 모듈 1과 모듈 2 모의 서버가 함께 시작된다. Ctrl+C로 종료한다. Python을 따로 지정할 수 있다.

```powershell
.\start_demo.ps1 -Python (Join-Path $env:USERPROFILE "anaconda3\python.exe")
```

기본 포트는 8000(웹·모듈 1), 8001(모듈 2 모의 서버)이다. 포트가 사용 중이면 `-Port 8100 -MockPort 8101`로 변경한다.

## 사용 흐름

1. 장병 목록에서 군번을 검색하고 선택한다.
2. 현재 기록, 목표 기록, `Goal − Now` 차이를 확인한다.
3. ‘새 사례’에서 군번·나이·키·체중·2분 체력 기록·3km 시간을 입력한다.
4. 저장 시 검증하고 BMI·하중비·목표를 계산한다. 중복 군번은 저장하지 않는다.
5. ‘모듈 2로 전송’으로 접수를 확인한다. 모의 서버는 운동 계획을 생성하지 않는다.

현재 웹 입력도 실제 개인정보가 없는 **가상의 사례**로 취급한다. 성별은 남성, 보직은 보병 소총수, 준비 하중은 15kg으로 고정한다. 장비·제한사항은 아직 수집하지 않으므로 모듈 2에 `null / not_collected`로 전달하며, 제한 없음으로 해석하지 않는다.

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

## 모듈 2 연결

친구에게 다음 파일을 전달하면 된다.

- [MODULE2_HANDOFF.md](docs/MODULE2_HANDOFF.md): 구현할 API와 의미
- [module2.openapi.json](docs/module2.openapi.json): OpenAPI 3.1 명세
- [module2_request.example.json](docs/module2_request.example.json): 운동 30종까지 포함한 전체 요청 예시
- [module2_mock.py](integration/module2_mock.py): 접수 서버 참고 구현

실제 모듈 2가 준비되면 주소만 바꾼다. 이 경우 모의 서버는 시작하지 않는다.

```powershell
.\start_demo.ps1 -Module2Url "http://127.0.0.1:9000"
```

모듈 2는 `GET /health`, `POST /api/v1/plans`를 구현한다. 현재 통합 범위는 요청 전송과 접수 응답 검증이다. 실제 운동 계획 생성, 계획 조회 API, Claude 호출 및 계획 검증·수정 루프는 모듈 2 담당이다.

## 배치 실행과 테스트

```powershell
# 기존 합성 원본 검증 → 목표 → 차이 → JSON 저장
python backend/module1/run_module1.py

# 새로운 군번 기준연도로 합성 원본 재생성 (기존 원본을 교체함)
python backend/module1/run_module1.py --generate --count 1000 --seed 42 --service-year 2022 --overwrite

# 선택 사항: 그래프도 생성
python backend/module1/run_module1.py --generate --overwrite --plots

# 모듈 1 및 API 통합 테스트
python -m unittest discover -s tests -v
python backend/module1/03_validate_and_compute.py --self-test
python backend/module1/02_generate_synthetic_soldiers.py --self-test

# 실제 HTTP 왕복 통신 확인: 임시 포트·임시 DB, 기존 데이터 변경 없음
python integration/smoke_test.py
```

배치 결과는 `data/validation_result.json`, `data/module2_input.json`에 저장된다. 입력 오류가 하나라도 있으면 전체 배치 계산을 차단하고 `status=failed, records=[]`로 저장하여 이전 성공 결과를 이번 결과로 오인하지 않도록 한다.

## 파일 구성

| 위치 | 역할 |
|---|---|
| `backend/module1/02_generate_synthetic_soldiers.py` | 군번·인구학·체격·2분 체력 합성 |
| `backend/module1/03_validate_and_compute.py` | 입력 검증, BMI·하중비 계산 |
| `backend/module1/module1_core.py` | 1급 목표, 차이 행렬, 공통 계약 검증 |
| `backend/module1/run_module1.py` | 배치 실행 |
| `backend/module1/04_build_goal_and_difference.py` | 동일 배치 실행의 별칭 |
| `backend/module1/storage.py` | SQLite 초기 적재·조회·추가·접수 이력 |
| `backend/module1/server.py` | 웹 제공 및 모듈 1 API |
| `backend/module1/module2_client.py` | 모듈 2 HTTP 전송 및 응답 확인 |
| `backend/module1/config/` | 목표 기준·공통 운동 30종·계획 규칙 |
| `frontend/` | 조회·직접 입력·목표 비교 화면 |
| `docs/openapi.json` | 웹↔모듈 1 API 명세 |
| `integration/` | 모의 모듈 2 및 통신 확인 |
| `tests/` | 계산·저장·계약·실패 처리 테스트 |

## 시제품 범위

운동의 명칭과 동작 출처, 시제품에서 정한 운동량·빈도 범위를 구분한다. 30종 운동표의 운동량·보완 대상 매핑과 주간 규칙은 검증된 개인별 처방이 아니다. 8주 계획은 여러 운동을 조합하여 1급 목표 및 15kg 훈련 준비를 지원하도록 요청하며, 달성을 보장하지 않는다.

서버는 같은 PC의 루프백 주소에 바인딩하는 개발용 구현이다. 다중 사용자 배포·로그인·실제 개인정보 운영은 이번 범위에 포함하지 않는다.


## Goal 정책 v2.0.0

API 계약은 `2.0.0`, 목표 기준 버전은 `rok_male_grade1_fixed_v2.0.0`이다. 목표 기록은 기준표의 고정값이며, 실제 운동 계획은 기준을 이미 충족한 종목의 성능을 낮추도록 처방하지 않는다. 기존 v1 서버는 재시작해야 새 Goal 계산이 반영된다. 저장된 장병 원 기록은 그대로 사용한다.

## GitHub에서 시작하기

```powershell
git clone https://github.com/techgyu/combat-fitness.git
cd combat-fitness
.\start_demo.ps1
```

이 저장소의 루트에 backend, frontend, docs, integration, tests가 위치한다. 합성 원본·메타데이터·통계표·그래프는 포함하며, 실행 중 생성되는 SQLite DB·로그·검증 보고서·배치 결과는 .gitignore로 제외한다. DB는 최초 실행 시 포함된 합성 원본에서 생성되고, 배치 결과는 run_module1.py로 재생성할 수 있다.
