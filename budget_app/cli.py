""" CLI 계층 - argparse 파싱 + 대화형 input() + 출력

사용자 입력을 받아 services를 부르고, 결과를 화면에 보여주는 것만 담당.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Callable, TypeVar

from budget_app.decorators import handle_errors, log_call, timed
from budget_app.errors import AppError
from budget_app.models import Transaction
from budget_app.services import BudgetService, check_date, parse_amount, parse_tags

DEFAULT_LIMIT = 10

T = TypeVar("T")


# ---------- 출력 헬퍼 ----------
def _print_rows(txs: list[Transaction]) -> None:
    if not txs:
        print("데이터 없음")
        return
    # 외부 라이브러리 없이 열 너비 맞추기
    rows = [[t.id, t.date, t.type, t.category, str(t.amount), t.memo, ",".join(t.tags)] for t in txs]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        cells = [c.rjust(w) if i == 4 else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths))]
        print(" | ".join(cells).rstrip(" |"))


def _ask(prompt: str, convert: Callable[[str], T], hint: str = "") -> T:
    """올바른 값이 들어올 때까지 재입력 요구"""
    while True:
        raw = input(prompt).strip()
        try:
            return convert(raw)
        except (AppError, ValueError) as e:
            print(f"[오류] {getattr(e, 'message', e)}")
            h = getattr(e, "hint", "") or hint
            if h:
                print(f"[힌트] {h}")


# ---------- 명령 핸들러 ----------
def cmd_add(svc: BudgetService, args: argparse.Namespace) -> int:
    def to_type(v: str) -> str:
        if v not in ("income", "expense"):
            raise AppError(f"허용되지 않은 type: {v!r}", "income 또는 expense")
        return v

    def to_category(v: str) -> str:
        svc.require_category(v)
        return v

    date = _ask("날짜(YYYY-MM-DD): ", check_date)
    tx_type = _ask("타입(income/expense): ", to_type)
    category = _ask("카테고리: ", to_category)
    amount = _ask("금액(양수): ", parse_amount)
    memo = input("메모(선택): ").strip()
    tags = parse_tags(input("태그(쉼표로 구분, 없으면 엔터): "))

    tx = svc.add(type=tx_type, date=date, amount=amount, category=category, memo=memo, tags=tags)
    print(f"[저장 완료] id={tx.id}")
    return 0


def cmd_list(svc: BudgetService, args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise AppError("--limit 은 1 이상이어야 합니다.", "예: --limit 5")
    _print_rows(svc.latest(args.limit))
    return 0


def cmd_search(svc: BudgetService, args: argparse.Namespace) -> int:
    _print_rows(svc.search(args.date_from, args.date_to, args.category, args.type, args.q, args.tag))
    return 0


def cmd_summary(svc: BudgetService, args: argparse.Namespace) -> int:
    if args.top <= 0:
        raise AppError("--top 은 1 이상이어야 합니다.", "예: --top 3")
    s = svc.summary(args.month)
    print(f"[{s.month} 요약]")
    if s.count == 0:
        print("데이터 없음")
    else:
        print(f"총 수입: {s.income}원")
        print(f"총 지출: {s.expense}원")
        print(f"잔액: {s.balance}원")
    if s.budget is not None:
        print(f"예산: {s.budget}원 (사용률 {s.usage_rate:.1f}%)")
        if s.expense > s.budget:
            print(f"[경고] 예산 초과! {s.expense - s.budget}원 초과했습니다.")
    if s.by_category:
        print(f"\n지출 TOP {args.top}")
        for i, (cat, amt) in enumerate(s.top(args.top), start=1):
            print(f"{i}) {cat} {amt}원")
    return 0


def cmd_budget_set(svc: BudgetService, args: argparse.Namespace) -> int:
    b = svc.set_budget(args.month, args.amount)
    print(f"[저장 완료] {b.month} 예산 {b.amount}원")
    return 0


def cmd_budget_show(svc: BudgetService, args: argparse.Namespace) -> int:
    check_date(args.month, "%Y-%m")
    b = svc.budgets.get(args.month)
    print(f"{args.month} 예산 {b.amount}원" if b else f"{args.month} 예산 없음")
    return 0


def cmd_category_add(svc: BudgetService, args: argparse.Namespace) -> int:
    name = args.name or input("카테고리명: ")
    svc.add_category(name)
    print(f"[저장 완료] category={name.strip()}")
    return 0


def cmd_category_list(svc: BudgetService, args: argparse.Namespace) -> int:
    for c in svc.categories.list():
        print(f"- {c}")
    return 0


def cmd_category_remove(svc: BudgetService, args: argparse.Namespace) -> int:
    name = args.name or input("삭제할 카테고리명: ").strip()
    svc.remove_category(name)
    print(f"[삭제 완료] category={name}")
    return 0


def cmd_update(svc: BudgetService, args: argparse.Namespace) -> int:
    changes: dict = {}
    if args.date is not None:
        changes["date"] = check_date(args.date)
    if args.type is not None:
        changes["type"] = args.type
    if args.category is not None:
        changes["category"] = args.category
    if args.amount is not None:
        changes["amount"] = parse_amount(args.amount)
    if args.memo is not None:
        changes["memo"] = args.memo
    if args.tags is not None:
        changes["tags"] = parse_tags(args.tags)
    svc.update(args.id, changes)
    print(f"[수정 완료] id={args.id}")
    return 0


def cmd_delete(svc: BudgetService, args: argparse.Namespace) -> int:
    svc.delete(args.id)
    print(f"[삭제 완료] id={args.id}")
    return 0


def cmd_import(svc: BudgetService, args: argparse.Namespace) -> int:
    imported, skipped, errors = svc.import_csv(Path(args.src))
    for e in errors:
        print(f"[건너뜀] {e}")
    print(f"[완료] imported={imported}, skipped={skipped}")
    return 0


def cmd_export(svc: BudgetService, args: argparse.Namespace) -> int:
    n = svc.export_csv(Path(args.out), args.month, args.date_from, args.date_to)
    print(f"[완료] {args.out} ({n} records)")
    return 0


# ---------- 파서 ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m budget_app", description="콘솔 가계부")
    p.add_argument("--data-dir", default="./data", help="저장 폴더 (기본: ./data)")
    p.add_argument("--verbose", action="store_true", help="실행 로그/소요시간 출력")
    # --data-dir 를 명령 뒤에 써도 인식되도록 각 명령에 공유 (SUPPRESS: 안 쓰면 위의 기본값 유지)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS, help="저장 폴더 (기본: ./data)")

    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    s = sub.add_parser("add", parents=[common], help="거래 추가 (대화형)")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("list", parents=[common], help="최신순 거래 목록")
    s.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"출력 건수 (기본 {DEFAULT_LIMIT})")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("search", parents=[common], help="조건 검색 (최신순)")
    s.add_argument("--from", dest="date_from", help="시작일 YYYY-MM-DD")
    s.add_argument("--to", dest="date_to", help="종료일 YYYY-MM-DD")
    s.add_argument("--category")
    s.add_argument("--type", choices=["income", "expense"])
    s.add_argument("--q", help="메모 키워드")
    s.add_argument("--tag")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("summary", parents=[common], help="월별 요약 + 예산 사용률")
    s.add_argument("--month", required=True, help="YYYY-MM")
    s.add_argument("--top", type=int, default=3, help="카테고리별 지출 TOP N (기본 3)")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("budget", help="월 예산 설정/조회")
    bsub = s.add_subparsers(dest="action", metavar="<action>")
    bsub.required = True
    b = bsub.add_parser("set", parents=[common], help="예산 설정")
    b.add_argument("--month", required=True, help="YYYY-MM")
    b.add_argument("--amount", required=True, help="양수 정수")
    b.set_defaults(func=cmd_budget_set)
    b = bsub.add_parser("show", parents=[common], help="예산 조회")
    b.add_argument("--month", required=True, help="YYYY-MM")
    b.set_defaults(func=cmd_budget_show)

    s = sub.add_parser("category", help="카테고리 관리")
    csub = s.add_subparsers(dest="action", metavar="<action>")
    csub.required = True
    c = csub.add_parser("add", parents=[common], help="카테고리 추가")
    c.add_argument("--name", help="생략 시 대화형 입력")
    c.set_defaults(func=cmd_category_add)
    c = csub.add_parser("list", parents=[common], help="카테고리 목록")
    c.set_defaults(func=cmd_category_list)
    c = csub.add_parser("remove", parents=[common], help="카테고리 삭제 (사용 중이면 거부)")
    c.add_argument("--name", help="생략 시 대화형 입력")
    c.set_defaults(func=cmd_category_remove)

    s = sub.add_parser("update", parents=[common], help="거래 수정 (옵션 방식)")
    s.add_argument("--id", required=True)
    s.add_argument("--date")
    s.add_argument("--type", choices=["income", "expense"])
    s.add_argument("--category")
    s.add_argument("--amount")
    s.add_argument("--memo")
    s.add_argument("--tags", help="쉼표 구분")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("delete", parents=[common], help="거래 삭제")
    s.add_argument("--id", required=True)
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("import", parents=[common], help="CSV 가져오기")
    s.add_argument("--from", dest="src", required=True, help="CSV 경로")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("export", parents=[common], help="CSV 내보내기")
    s.add_argument("--out", required=True, help="CSV 경로")
    s.add_argument("--month", help="YYYY-MM")
    s.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    s.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    s.set_defaults(func=cmd_export)

    return p


@handle_errors
@log_call
@timed
def run(args: argparse.Namespace) -> int:
    svc = BudgetService(Path(args.data_dir))
    return args.func(svc, args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # 잘못된 옵션은 argparse가 exit code 2로 종료
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="[log] %(message)s")
    return run(args)
