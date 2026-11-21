# 모듈 2 연동 규격 v2.0.0

모듈 1은 검증된 장병 원 기록과 1급 목표, Goal − Now 차이, 프로필, 하중 참고값, 동일 버전 운동표·규칙을 HTTP JSON으로 전달한다.

## 구현할 API

### GET /health

HTTP 200:

```json
{"status":"ok","service":"module2","mode":"real","contract_version":"2.0.0"}
```

### POST /api/v1/plans

Content-Type은 application/json이다. [전체 예시](module2_request.example.json)와 [OpenAPI](module2.openapi.json)를 참고한다.

| 필드 | 의미 |
|---|---|
| contract_version | 2.0.0 |
| request_id | 요청마다 새 UUID. 응답에 그대로 반영 |
| module1_result.soldier_id | 군번. 연도 2자리-숫자 8자리 |
| module1_result.difference_matrix | Goal − Now, 1×4 |
| module1_result.now_matrix / goal_matrix | 차이를 해석할 원 기록과 목표, 각 1×4 |
| module1_result.profile | 변하지 않는 체격·나이·성별·보직 |
| module1_result.load_context | 15kg 조건, 실제 하중비, reference_only |
| module1_result.training_context | 장비·제한사항은 현재 미수집. null을 제한 없음으로 처리하지 않음 |
| module1_result.versions | 목표표·운동표·규칙·측정 조건·검증기 버전 |
| module1_result.resources_sha256 | 전송된 공통 자료의 해시 |
| shared_resources | target_criteria, exercise_catalog, planning_rules |

열 순서는 `pushups_2min / situps_2min / run_3km_seconds / load_to_body_weight_ratio`이다. 하중비를 제외한 기록은 2분 횟수·초 단위를 사용한다. 점수가 아니며, 서로 다른 단위를 그대로 합쳐 우선순위 점수로 쓰지 않는다.

예: `[[16,18,-148,0]]`은 팔굽혀펴기 +16회, 윗몸일으키기 +18회, 3km −148초를 의미한다. 4열이 0이어도 15kg 훈련이 가능하다는 의미는 아니다. 실제 하중비는 load_context를 참고한다. Goal은 현재 기록과 관계없이 연령별 1급 기준값으로 고정하며 차이를 0으로 자르지 않는다. 횟수 차이의 음수와 달리기 차이의 양수는 이미 기준보다 좋은 기록임을 뜻한다. 예를 들어 23세·75kg, 현재 90회·100회·700초이면 Goal은 64회·78회·812초이고 차이는 [[-26,-22,112,0]]이다. 이러한 초과 달성은 운동 수행능력을 낮추라는 지시가 아니다.

접수 응답은 HTTP 202와 다음 JSON으로 반환한다.

```json
{
  "contract_version": "2.0.0",
  "request_id": "요청의 request_id와 동일",
  "receipt_id": "module2가 부여한 접수 식별자",
  "status": "accepted",
  "mode": "real"
}
```

접수 확인은 계획 생성 완료를 의미하지 않는다. 계획 조회·완료 응답은 모듈 2 구현 시 추가 협의한다. 모듈 1은 request_id, 계약 버전, accepted 상태, mode 및 receipt_id를 확인하고 실패를 사용자에게 표시한다. 자동 재시도는 하지 않으며 재전송 시 새 요청이 생성된다.

형식 오류는 422 등 비성공 HTTP 코드로 반환한다.

```json
{"error":{"code":"invalid_contract","message":"오류 설명","details":[]}}
```

## 모듈 2가 수행할 작업

1. 세 체력 기록의 차이와 단위를 해석한다. 하중비는 별도 참고 정보로 사용한다.
2. 고정된 1급 기준과 현재 기록을 비교하여, 미달 종목의 개선과 충족 종목의 체력 유지 및 15kg 군장 훈련 준비를 위한 8주 계획을 생성한다.
3. 전달된 운동 30종에서 매주 여러 종목을 선택한다. 운동표 버전과 근거 ID를 유지한다.
4. 장비·제한사항이 미수집이면 추가 확인 또는 제한된 시연 조건을 명시한다.
5. 계획의 운동량·빈도·구성·근거를 공통 규칙으로 검증하고, 위반 시 최대 두 번 수정한다.
6. 계획·검증 결과·수정 이력을 제공한다.

운동표의 허용 범위와 주간 규칙은 시제품 가정이다. 통신 테스트 성공은 실제 계획 검증이나 8주 효과 검증이 아니다.

## 직접 테스트

```powershell
# 터미널 1: 모의 모듈 2
python integration/module2_mock.py --port 8001

# 터미널 2: 예시 JSON 전송
$body = Get-Content -LiteralPath docs/module2_request.example.json -Raw -Encoding UTF8
Invoke-RestMethod -Uri http://127.0.0.1:8001/api/v1/plans -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

# 실제 모듈 2 연동
.\start_demo.ps1 -Module2Url http://127.0.0.1:9000
```

모의 서버는 계약 버전·1×4 형식·목표·차이 계산·군번·기록·공통 자료 버전을 검증한 뒤 `mode=mock, plan=null`을 반환한다.


## v2 변경 사항

기존 v1의 max/min 목표 조정과 차이 부호 제한을 제거했다. Goal의 세 기록은 반드시 reference_records와 같아야 한다. 모듈 1과 모듈 2 모두 v2 계약을 사용해야 한다. 기준 초과 사례는 [module2_request.above_grade1.example.json](module2_request.above_grade1.example.json)을 참고한다.
