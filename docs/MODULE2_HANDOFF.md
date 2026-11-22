# 모듈 1·2 통합 규격 v2.0.0

## 실행 경로

웹 → 모듈 1 API → 모듈 2 `/api/v1/plans` → 입력 검증 → Claude 생성 → 계획 검증 → 최대 2회 수정 → 모듈 1 SQLite 저장 → 웹 표시.

`start_demo.ps1`은 실제 모듈 2를 기본 실행한다. `-MockModule2`는 통신 접수만 확인하는 명시적 선택이다. Claude API 키는 저장소 루트 `.env`의 `ANTHROPIC_API_KEY`로 설정한다. 키는 요청 데이터·브라우저·결과 로그에 포함하지 않는다.

## 입력

공개 요청은 `contract_version`, `request_id`, `module1_result`, `shared_resources`를 가진다. 전체 예시는 `module2_request.example.json`과 `module2_request.above_grade1.example.json`이다.

- `module1_result`의 Now·Goal·차이 행렬은 각각 1×4다.
- 열은 `pushups_2min`, `situps_2min`, `run_3km_seconds`, `load_to_body_weight_ratio` 순서다.
- 단위는 `repetitions/120s`, `repetitions/120s`, `s`, `dimensionless`다.
- Goal은 항상 연령별 1급 기준이다. 횟수의 음수 차이와 달리기의 양수 차이는 기준 초과이며 현재 수준 유지 대상으로 처리한다.
- 원 차이는 수정하거나 0으로 자르지 않는다. 계획용 `needs.amount`만 개선 필요량을 나타내며 기준 충족·초과 시 0이다.
- 하중비는 참고값이고 차이의 네 번째 값은 0이다.
- 군번은 `YY-NNNNNNNN` 형식이며 남성 18~29세·보병 소총수·합성 데이터만 받는다.
- 운동 30종·근거·규칙의 원본은 `backend/module2/data`이다. 모듈 1은 같은 원본을 기존 공개 필드 구조로 변환한다. 모듈 2는 해시뿐 아니라 로컬 공통 자료와의 내용 일치도 검증한다.

`bridge.py`는 검증 후 내부 planner 입력으로 필드명과 단위 표기만 변환한다. 수치·군번·부호는 보존한다. `/plan`은 모듈 2 단독 입력을 위한 경로이며 전체 시스템에서는 사용하지 않는다.

## 응답

`GET /health`: `status=ok`, `mode=real`, `contract_version=2.0.0`, `generation_ready`, `model`, `versions`, `message`를 반환한다. 키가 없어도 서버 상태는 정상이며 `generation_ready=false`다. 이 필드는 키 설정 여부로, 실제 키의 유효성은 생성 요청에서 확인한다.

`POST /api/v1/plans`: 실제 서버는 생성과 검증이 끝난 뒤 HTTP 200을 반환한다.

```json
{
  "contract_version": "2.0.0",
  "request_id": "요청의 식별자",
  "receipt_id": "서버의 접수 식별자",
  "status": "accepted",
  "mode": "real",
  "generation_status": "passed 또는 failed",
  "plan": [],
  "result": {
    "status": "passed 또는 failed",
    "soldier": {},
    "records": [],
    "summary": "계획 요약",
    "plan": [],
    "validation": {},
    "history": [],
    "revisions_used": 0
  },
  "assumptions": [],
  "resources_sha256": "입력 자료 해시"
}
```

위 JSON은 필드 구조 설명용이며 빈 계획은 검증 통과를 의미하지 않는다. `accepted`는 통신 접수, `generation_status`는 계획 검증 결과다. 수정 한도 초과와 모델 거부는 `failed`로 반환한다. 모의 서버만 HTTP 202와 `plan=null`을 반환한다.

오류는 `error.code`, `error.message`, `error.details` 구조다. 입력 오류 422, 키 미설정·호출 한도·연결 실패 503, 인증·제공자 오류 502, 응답 시간 초과 504를 사용한다. 모듈 1은 알려진 오류를 웹에 전달하며 키나 제공자 원본 오류는 노출하지 않는다.

## 결과 보관 및 표시

모듈 1의 `deliveries` 테이블에 생성 결과를 보관한다. 장병 조회 응답의 `latest_plan`으로 최근 결과를 다시 표시한다. 현재 구조는 입력 기록 수정 기능이 없는 합성 사례용이다. 검증 미통과 결과는 명확히 미통과로 표시한다.

체력검정 기록은 계획 수립의 바탕 자료다. 보병 소총수의 군장 준비에 필요한 하체·코어·유산소·하중 적응·회복 운동도 후보 목록에서 함께 선택한다. 등록 규칙 준수 여부를 확인하는 시제품이며, 실제 8주 향상이나 군장 수행능력을 보장하지 않는다.
