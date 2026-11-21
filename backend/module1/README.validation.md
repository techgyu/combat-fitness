# 03. 입력 검증 및 BMI·하중비 계산

이 단계는 02번 스크립트가 생성한 합성 장병 데이터를 읽어 입력 오류를 확인하고,
모든 장병의 입력이 유효할 때 BMI와 하중 대 체중비를 계산한다.

- 코드: `03_validate_and_compute.py`
- 기본 입력: `data/synthetic_soldiers.json`
- 출력: `data/validation_result.json`
- Python 3.10 이상, 표준 라이브러리만 사용한다. 별도 패키지 설치는 필요 없다.
- 원본 합성 데이터와 02번 스크립트는 수정하지 않는다.

## 실행

`backend/module1` 폴더에서 실행한다.

```powershell
conda activate combat-fitness
python .\03_validate_and_compute.py
```

기본 입력·출력은 실행 위치와 관계없이 **이 스크립트 옆의 data 폴더**를 사용한다.
명시적으로 지정한 상대 경로는 현재 터미널 위치를 기준으로 해석한다.

CSV를 입력으로 쓰거나 출력 위치를 바꾸려면 다음과 같이 실행한다.

```powershell
python .\03_validate_and_compute.py --input .\data\synthetic_soldiers.csv
python .\03_validate_and_compute.py --output .\data\validation_custom.json
```

출력 파일은 매 실행의 결과로 교체한다. 원본 파일을 출력으로 지정하면 오류로 중단한다.

## 처리 순서

1. JSON 또는 CSV를 읽는다. JSON 최상위는 장병 객체들의 배열이어야 한다.
2. 각 장병의 필수값·숫자 형식·고정 조건·단위를 검증하고 ID 중복을 확인한다.
3. 달리기 기록을 초 단위로 통일한다. 이때 숫자 크기만으로 단위를 추측하지 않는다.
4. 한 건이라도 오류가 있으면 계산하지 않고 오류 보고서를 저장한다.
5. 전부 통과하면 BMI와 하중비를 계산하고 정상 결과를 저장한다.

달리기 단위 변환은 검증 과정에 포함된다. **BMI·하중비 산출은 전체 입력 검증을 통과한 뒤에만 수행한다.**
빈 배열, JSON 문법 오류, 중복 JSON 키, 잘못된 CSV 열 수, 파일을 읽지 못하는 경우도 실패로 처리한다.

## 필드와 검증 규칙

| 필드 | 규칙 | 선택 이유 |
| --- | --- | --- |
| soldier_id | YY-NNNNNNNN 형식의 고유 군번 | DB 기본 키 및 조회 키 |
| is_synthetic | true; CSV에서는 True/true 문자열 허용 | 이 단계가 합성 데이터임을 확인 |
| age | 18~29의 정수 | 현재 생성기의 시연 범위와 일치 |
| age_basis | 있으면 calendar_year_minus_birth_year; 생략 시 같은 값 적용 | 기존 생성기의 연나이 정의 유지 |
| sex | male | 현재 시연의 고정 조건 |
| role | infantry_rifleman | 현재 시연의 고정 조건 |
| height_cm | 100~250의 유한한 숫자, cm | m 값을 cm 필드에 잘못 입력하는 오류 등을 탐지 |
| weight_kg | 20~350의 유한한 숫자, kg | g 값을 kg 필드에 잘못 입력하는 오류 등을 탐지 |
| combat_load_kg | 15 | 현재 시연의 고정 하중 |
| pushups_2min | 0 이상의 정수 | 2분 기록, 0회도 정상 테스트 사례 |
| situps_2min | 0 이상의 정수 | 2분 기록, 0회도 정상 테스트 사례 |
| run_3km_seconds 또는 run_3km_time | 둘 중 하나; 변환 후 60~7,200초 | 누락·중복 표현·명백한 단위 실수를 탐지 |
| bmi | 선택; 있으면 0.01 이상의 유한한 숫자 | 최종 BMI는 항상 키·체중으로 재계산 |

CSV의 숫자 문자열은 숫자로 변환한다. NaN·무한대·참/거짓을 숫자로 받지 않는다.
단위가 붙은 문자열(`175cm`, `75kg`)도 자동 해석하지 않는다.

**이 표의 나이 범위와 키·체중·시간 범위는 프로젝트의 입력 검증 설정이다.**
공식 입영 자격 기준이나 의학적 정상 범위가 아니다.
02번 생성기가 만드는 범위를 포함하도록 넓게 잡았으며, 범위 안에 들어온다는 사실만으로 단위가 올바르다고 증명되지는 않는다.
예를 들어 파운드로 기록한 체중을 kg 필드에 숫자만 넣으면 자동 탐지가 어려우므로 입력자는 필드의 단위를 지켜야 한다.

명시적인 단위·측정 조건을 함께 전달할 경우에도 확인한다.

| 선택 필드 | 허용값 |
| --- | --- |
| height_unit | cm |
| weight_unit / combat_load_unit | kg |
| pushups_duration_seconds / situps_duration_seconds | 120 |
| run_distance_m | 3000 |
| baseline_test_load_kg | 0 |

기존 합성 체력 기록은 하중 없이 측정한 것으로 설정되어 있다.
15kg은 후속 훈련 계획의 참고 조건이며, 이 단계가 기록을 15kg 착용 기록으로 변환하는 것은 아니다.

기존 생성기의 body_reference_group, fitness_scenario는 문자열이면 출력에도 보존한다.
그 밖의 임의 필드는 출력에 복사하지 않는다.

## 달리기 입력 예시

기존 생성 파일은 이미 첫 번째 형식이므로 변환을 위해 수정할 필요가 없다.
아래는 한 장병 객체의 달리기 필드 부분만 발췌한 예시다.

| 입력 | 정규화 결과 |
| --- | --- |
| `"run_3km_seconds": 1110` | 1110초 |
| `"run_3km_time": "18:30"` | 1110초 |
| `"run_3km_time": 18.5, "run_3km_unit": "min"` | 1110초 |
| `"run_3km_time": 1110, "run_3km_unit": "s"` | 1110초 |

- 숫자형 run_3km_time에 단위가 없으면 실패한다.
- run_3km_seconds와 run_3km_time을 동시에 채우면 실패한다.
- `18:60`처럼 초 부분이 60 이상이거나 `18:3`처럼 형식이 다르면 실패한다.
- 분:초 문자열의 단위는 생략하거나 mm:ss로 지정한다.
- 출력에는 run_3km_seconds만 남긴다.

## 계산식

```text
BMI = weight_kg / (height_cm / 100)^2
load_ratio = combat_load_kg / weight_kg
load_ratio_percent = load_ratio × 100
```

키 175cm, 체중 75kg, 전투하중 15kg인 경우:

| 결과 | 값 |
| --- | --- |
| bmi | 24.49 |
| load_ratio | 0.2 |
| load_ratio_percent | 20.0 |

BMI는 소수점 둘째 자리, 하중비는 여섯째 자리, 백분율은 둘째 자리까지 저장한다.
백분율은 반올림 전 하중비로 계산한다.

기존 BMI는 파생값이므로 최종 계산에 사용하지 않는다.
기존 값이 없으면 새로 계산한다. 기존 값이 유효한 숫자이지만 재계산 값과 0.05보다 크게 다르면
경고를 남기고 재계산 값으로 교체한다. 반면 음수·무한대 등 잘못된 BMI 입력은 검증 오류다.

## 결과 읽기

통과한 결과의 구조:

```json
{
  "status": "passed",
  "summary": {
    "total_records": 1000,
    "valid_records": 1000,
    "invalid_records": 0,
    "computed_records": 1000,
    "error_count": 0,
    "warning_count": 0
  },
  "records": ["실제 파일에는 검증·계산을 마친 장병 객체가 들어갑니다"],
  "errors": [],
  "warnings": []
}
```

위 배열의 문자열은 구조 설명용이다. 실제 records에는 장병 객체가 들어간다.
그 밖에 스키마 버전, 실행 시각, 입력 경로, 읽은 원본의 SHA-256, 단위, 검증 정책을 기록한다.
파일 읽기·파싱에 실패하면 SHA-256은 null일 수 있다.

실패하면 status는 failed, records는 빈 배열, computed_records는 0이다.
errors에 장병 순번(row), ID, 필드, 오류 코드와 사유를 기록한다.
row는 **첫 번째 장병이 1인 데이터 순번**이며 JSON 줄 번호가 아니다. CSV 헤더도 세지 않는다.

valid_records는 입력 검증을 통과한 개수다. 일부 장병이 통과해도 하나라도 실패하면
전체 계산을 중단하므로 computed_records는 0이다. 파일 전체를 파싱하지 못한 경우 총 레코드 수를 알 수 없어 0으로 기록한다.

후속 단계는 반드시 아래 조건을 확인한 후 records를 사용한다.

```python
if report["status"] != "passed":
    raise ValueError("입력 검증에 실패했습니다.")
records = report["records"]
```

보고서는 임시 파일에 완전히 쓴 뒤 교체한다. 실패 보고서도 같은 출력 경로를 갱신하므로,
이전 성공 기록이 이번 실행의 성공으로 남지 않는다.
다만 파일 권한 문제 등으로 보고서 자체를 저장하지 못하면 기존 파일이 남을 수 있으므로
프로세스 종료 코드와 터미널 오류도 확인해야 한다.

| 종료 코드 | 의미 |
| --- | --- |
| 0 | 검증·계산·저장 성공 |
| 1 | 검증 실패; 실패 보고서 저장 완료 |
| 2 | 경로 문제 또는 보고서 저장 등 실행 실패 |

## 자체 점검

```powershell
python .\03_validate_and_compute.py --self-test
```

정상 계산, 0회 기록, BMI 재계산, 달리기 표현 변환, 누락·잘못된 단위·비유한 숫자,
고정 조건 위반, 중복 ID, CSV 처리, 원본 보호, 이전 성공 보고서를 실패 보고서로 교체하는 동작을 점검한다.
자체 점검은 임시 폴더만 사용하며 실제 data 폴더의 결과를 변경하지 않는다.

2026-11-21: 자체 테스트 8개와 1,000명 검증을 통과했다. 목표·차이 및 API 테스트는 프로젝트 tests 폴더에서 별도로 수행했다.

## 후속 처리

`run_module1.py`는 원본 JSON/CSV를 이 검증기에 넣은 뒤 같은 프로세스에서 목표·차이를 계산한다. 입력이 하나라도 잘못되면 `module2_input.json`도 실패 결과로 바꾼다. `04_build_goal_and_difference.py`는 동일한 배치 실행의 별칭으로 원본 JSON/CSV를 받는다. 검증 결과 파일을 다시 원본 입력으로 넣지 않는다. 1분 필드가 섞인 입력은 거부한다.
