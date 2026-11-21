# 합성 데이터 및 통계표

먼저 `../02_generate_synthetic_soldiers.py`를 실행한다.

| 파일 | 구분 | 설명 |
| --- | --- | --- |
| reference_age_counts_2024.csv | 공식 집계 전사본 | 병무청 2024년 징집병·모집병 연령별 인원. 이미 저장한 참고표 |
| synthetic_soldiers.csv | 실행 시 생성 | 장병별 합성 입력값 |
| synthetic_soldiers.json | 실행 시 생성 | 동일 레코드의 JSON |
| generation_metadata.json | 실행 시 생성 | 출처, 가정, 생성 설정과 요약 |
| summary_statistics.csv | 실행 시 생성 | 수치 항목별 평균·표준편차·백분위·최솟값·최댓값 |
| age_distribution.csv | 실행 시 생성 | 나이별 인원·실제 비율·모델 기대 비율 |
| fitness_distribution.csv | 실행 시 생성 | 체력 테스트 시나리오별 인원·비율 |

`reference_age_counts_2024.csv`를 합성 장병의 통계표로 해석하지 않는다.
나머지 파일은 스크립트 실행에 성공해야 만들어진다.
근거와 생성 방식은 `../README.synthetic.md`를 참고한다.

## 통계 이미지

기본 실행은 `plots/` 폴더에 PNG 6장을 함께 저장한다.

| 파일 | 내용 |
| --- | --- |
| plots/01_age_distribution.png | 실제 연령 비율과 모델 기대 비율 |
| plots/02_body_distributions.png | 키·체중·BMI 분포 |
| plots/03_fitness_distributions.png | 체력 기록 분포 |
| plots/04_height_weight.png | 키–체중 관계와 BMI |
| plots/05_fitness_scenarios.png | 체력 테스트 시나리오 구성 |
| plots/06_summary_table.png | 요약 통계표 이미지 |

기존 데이터로 이미지만 만들려면 `module1` 폴더에서 실행한다.

```powershell
python .\02_generate_synthetic_soldiers.py --plots-only
```

PNG가 이미 있으면 `--overwrite`를 추가한다. 이 모드는 기존 데이터 파일을 바꾸지 않는다.
Matplotlib 설치가 필요하며 `python -m pip install -r requirements-plots.txt`로 설치한다.
그래프에서 3km 시간은 분 단위로 표시하고, 원본 데이터·CSV 통계는 초 단위를 유지한다.

## 현재 실행 결과 및 DB

현재 합성 원본은 1,000명, seed 42, 군번 기준연도 2026이며 2분 체력 기록을 사용한다.

| 파일 | 역할 |
|---|---|
| validation_result.json | 입력 검증·BMI·하중비 결과 |
| module2_input.json | 1급 목표·Goal − Now와 공통 운동표를 포함한 배치 결과 |
| soldiers.sqlite3 | 웹에서 사용하는 장병 DB. 최초 합성 적재 후 웹 입력을 누적 보관 |

군번 `soldier_id`는 `26-00000001` 같은 고유 키다. CSV/JSON 재생성은 이미 초기화된 DB를 교체하지 않는다. 다른 원본으로 시작하려면 server.py의 --db에 새 파일 경로를 지정한다.
