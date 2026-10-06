# 콘솔 가계부 (budget_app)

파일(JSONL) 기반 콘솔 가계부. 제너레이터 스트리밍, 데코레이터 분리, 타입 힌트, 계층 분리를 적용했다.
Python 3.10 이상, 표준 라이브러리만 사용.

## 실행 방법

```bash
python3 -m budget_app <command> [options]
python3 -m budget_app --help            # 전체 명령
python3 -m budget_app <command> --help  # 명령별 사용법
```

공통 옵션 (명령 앞에 둔다)

| 옵션 | 설명 |
| --- | --- |
| `--data-dir <경로>` | 저장 폴더 변경 (기본 `./data`) |
| `--verbose` | 실행 로그 / 소요 시간 출력 |

종료 코드: 정상 `0`, 처리 오류 `1`, 파일 오류·잘못된 옵션 `2`, 입력 중단 `130`.
오류는 스택트레이스 대신 `[오류] 원인` + `[힌트] 해결 방법`으로 출력한다.

## 저장 파일 위치 / 형식

기본 폴더 `./data/` 아래 JSONL(한 줄 = JSON 1건, UTF-8) 파일 3개로 분리 저장한다. 첫 실행 시 폴더와 파일 3개가 자동 생성된다.
`--data-dir`는 명령 앞뒤 어디에 써도 된다 (`python3 -m budget_app list --data-dir ./mydata`).

| 파일 | 한 줄 예시 |
| --- | --- |
| `transactions.jsonl` | `{"id": "TX-000001", "type": "expense", "date": "2024-01-15", "amount": 15000, "category": "food", "memo": "점심", "tags": ["meal"]}` |
| `categories.jsonl` | `{"name": "food"}` |
| `budgets.jsonl` | `{"month": "2024-01", "amount": 500000}` |

- **기본 카테고리 (안 A)**: `categories.jsonl`이 없거나 비어 있으면 `food, transport, rent, salary, etc`를 자동 생성한다.
- **원자적 저장**: update / delete / 예산 변경은 임시 파일(`*.tmp`)에 전부 쓴 뒤 `os.replace`로 교체한다. 쓰는 도중 종료돼도 원본이 깨지지 않고, 중단된 임시 파일은 정리된다. add는 맨 뒤에 한 줄 append.
- **스트리밍**: 파일을 한 번에 읽지 않고 제너레이터로 한 줄씩 처리한다. `list --limit N`은 `heapq.nlargest`로 흘려 메모리에 N건만 유지한다.
- **손상된 데이터**: 깨진 줄이 있으면 스택트레이스 대신 파일과 레코드 위치를 알려주고 종료한다(exit 1).

## 주요 명령 예시

```bash
# 거래 추가 (대화형, 잘못 입력하면 재입력 요구)
python3 -m budget_app add
# 날짜(YYYY-MM-DD): 2024-01-15
# 타입(income/expense): expense
# 카테고리: food
# 금액(양수): 15000
# 메모(선택): 점심
# 태그(쉼표로 구분, 없으면 엔터): meal
# [저장 완료] id=TX-000001

# 목록 (최신순, 기본 10건)
python3 -m budget_app list --limit 3

# 검색 (조건 조합 가능, 최신순)
python3 -m budget_app search --from 2024-01-01 --to 2024-01-31 --category food --type expense --q 점심 --tag meal

# 예산 설정 / 조회
python3 -m budget_app budget set --month 2024-01 --amount 500000
python3 -m budget_app budget show --month 2024-01

# 월별 요약 (총수입/총지출/잔액 + 지출 TOP N + 예산 사용률/초과 경고)
python3 -m budget_app summary --month 2024-01 --top 3

# 카테고리 관리 (--name 생략 시 대화형 입력)
python3 -m budget_app category list
python3 -m budget_app category add --name hobby
python3 -m budget_app category remove --name hobby   # 사용 중인 거래가 있으면 삭제 거부

# 수정 (옵션 방식으로 고정 - 안 A): 지정한 필드만 바뀐다
python3 -m budget_app update --id TX-000001 --amount 20000 --memo 저녁 --tags meal,dinner

# 삭제
python3 -m budget_app delete --id TX-000001

# CSV 내보내기 / 가져오기
python3 -m budget_app export --out export.csv --month 2024-01
python3 -m budget_app export --out export.csv --from 2024-01-01 --to 2024-03-31
python3 -m budget_app import --from import.csv
```

### 정책 정리

| 항목 | 결정 |
| --- | --- |
| 저장 포맷 | JSONL |
| update 방식 | 옵션 기반 (`update --id ... [--date] [--type] [--category] [--amount] [--memo] [--tags]`) |
| 빈 카테고리 | 기본 카테고리 자동 생성 |
| 사용 중 카테고리 삭제 | 거부 (거래를 다른 카테고리로 update 하거나 delete 후 재시도) |
| 없는 id | `[오류] 없는 데이터입니다` 출력, exit 1 |
| 최신순 정렬 | 날짜 내림차순, 같은 날짜면 나중에 등록한 것 먼저 (list / search 공통) |

## import / export CSV 스키마

UTF-8, 헤더 포함.

| column | required | 설명 |
| --- | --- | --- |
| date | Y | YYYY-MM-DD |
| type | Y | income / expense |
| category | Y | 등록된 카테고리 |
| amount | Y | 양수 정수 |
| memo | N | 문자열 |
| tags | N | 쉼표(,) 구분 문자열 |

```csv
date,type,category,amount,memo,tags
2024-01-15,expense,food,15000,점심,"meal,lunch"
2024-01-14,income,salary,3000000,,
```

- import는 행 단위로 검증한다. 잘못된 행(날짜 형식, 음수 금액, 미등록 카테고리 등)은 건너뛰고 사유를 출력한 뒤 `imported=N, skipped=M`을 보여준다.
- id는 import 시 새로 발급된다.
- export는 `--month` 또는 `--from`/`--to` 중 하나 이상이 필수다.

## 모듈 구조 (계층별 책임)

```
budget_app/
├── __main__.py   # 진입점: python -m budget_app → cli.main()
├── cli.py        # CLI: argparse 파싱, 대화형 input(), 출력
├── services.py   # 서비스: 검증 규칙, 검색 필터(제너레이터 체인), 요약/예산 계산, CSV 입출력
├── storage.py    # 저장소: JSONL 스트리밍 읽기, append, 원자적 재작성
├── models.py     # 모델: Transaction / Budget dataclass + 자기 검증(__post_init__)
├── decorators.py # 공통 관심사: @handle_errors(예외→메시지+종료코드), @log_call, @timed
└── errors.py     # AppError(메시지 + 힌트)
```

의존 방향은 위에서 아래로만 흐른다 (cli → services → storage → models). 아래 계층은 위 계층을 모른다.
