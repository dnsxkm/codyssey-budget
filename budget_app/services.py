""" 서비스 계층 - 비즈니스 규칙 + 계산

storage가 '파일 다루기'라면 services는 '규칙과 계산'.
CLI는 이 계층만 부르고, 파일 형식은 몰라도 된다.
"""

from __future__ import annotations

import csv
import heapq
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from budget_app.errors import AppError
from budget_app.models import Budget, Transaction
from budget_app.storage import BudgetStore, CategoryStore, TransactionRepository

CSV_COLUMNS = ["date", "type", "category", "amount", "memo", "tags"]


@dataclass
class Summary:
    month: str
    income: int = 0
    expense: int = 0
    count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    budget: int | None = None

    @property
    def balance(self) -> int:
        return self.income - self.expense

    @property
    def usage_rate(self) -> float | None:
        """예산 대비 지출 사용률(%). 예산 없으면 None"""
        if not self.budget:
            return None
        return self.expense / self.budget * 100

    def top(self, n: int) -> list[tuple[str, int]]:
        return sorted(self.by_category.items(), key=lambda kv: kv[1], reverse=True)[:n]


# ---------- 검증 헬퍼 ----------
def check_date(value: str, fmt: str = "%Y-%m-%d") -> str:
    pattern = r"\d{4}-\d{2}-\d{2}" if fmt == "%Y-%m-%d" else r"\d{4}-\d{2}"
    try:
        if not re.fullmatch(pattern, value):  # strptime은 2024-1-1도 통과시켜서 자릿수 고정
            raise ValueError
        datetime.strptime(value, fmt)
    except ValueError:
        example = "2024-01-15" if fmt == "%Y-%m-%d" else "2024-01"
        raise AppError(f"날짜 형식이 올바르지 않습니다: {value!r}", f"예: {example}")
    return value


def parse_amount(value: str | int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise AppError(f"금액은 정수여야 합니다: {value!r}", "예: 15000")
    if n <= 0:
        raise AppError(f"금액은 양수여야 합니다: {n}", "0보다 큰 정수를 입력하세요.")
    return n


def parse_tags(value: str | None) -> list[str]:
    """'a, b,c' -> ['a', 'b', 'c']"""
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


# ---------- 서비스 ----------
class BudgetService:
    def __init__(self, data_dir: Path) -> None:
        self.txs = TransactionRepository(data_dir)
        self.categories = CategoryStore(data_dir)  # 비어 있으면 기본 카테고리 자동 생성
        self.budgets = BudgetStore(data_dir)
        for path in (self.txs.path, self.budgets.path):  # 첫 실행 시 저장 파일 3개 모두 생성
            path.touch(exist_ok=True)

    # --- 카테고리 ---
    def require_category(self, name: str) -> None:
        if name not in self.categories.list():
            raise AppError(
                f"등록되지 않은 카테고리: {name!r}",
                f"사용 가능: {', '.join(self.categories.list())} / 새로 등록: category add",
            )

    def add_category(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise AppError("카테고리명이 비어 있습니다.", "예: food")
        if not self.categories.add(name):
            raise AppError(f"이미 존재하는 카테고리: {name!r}")

    def remove_category(self, name: str) -> None:
        """사용 중인 카테고리는 삭제를 막는다(정책)."""
        used = sum(1 for t in self.txs.stream() if t.category == name)
        if used:
            raise AppError(
                f"카테고리 {name!r}를 사용하는 거래가 {used}건 있어 삭제할 수 없습니다.",
                "해당 거래를 update --category 로 바꾸거나 delete 한 뒤 다시 시도하세요.",
            )
        if not self.categories.remove(name):
            raise AppError(f"없는 카테고리: {name!r}", "category list 로 목록을 확인하세요.")

    # --- 거래 CRUD ---
    def add(self, type: str, date: str, amount: int, category: str,
            memo: str = "", tags: list[str] | None = None) -> Transaction:
        self.require_category(category)
        tx = Transaction(id=self.txs.next_id(), type=type, date=date, amount=amount,  # type: ignore[arg-type]
                         category=category, memo=memo, tags=tags or [])
        self.txs.append(tx)
        return tx

    def update(self, tx_id: str, changes: dict) -> None:
        if not changes:
            raise AppError("수정할 필드가 없습니다.", "예: update --id TX-000001 --amount 20000")
        if "category" in changes:
            self.require_category(changes["category"])
        if not self.txs.update(tx_id, changes):
            raise AppError(f"없는 데이터입니다: id={tx_id}", "list 로 id를 확인하세요.")

    def delete(self, tx_id: str) -> None:
        if not self.txs.delete(tx_id):
            raise AppError(f"없는 데이터입니다: id={tx_id}", "list 로 id를 확인하세요.")

    # --- 조회 (스트리밍) ---
    def latest(self, limit: int) -> list[Transaction]:
        """최신순(날짜 내림차순, 같은 날짜면 나중 등록 먼저) limit건.

        heapq.nlargest는 스트림을 한 건씩 소비하면서 상위 limit건만 힙에 유지한다
        -> 파일 전체를 메모리에 올리지 않는다.
        """
        return heapq.nlargest(limit, self.txs.stream(), key=_newest_key)

    def search(self, date_from: str | None = None, date_to: str | None = None,
               category: str | None = None, type: str | None = None,
               q: str | None = None, tag: str | None = None) -> list[Transaction]:
        """조건 필터를 제너레이터 체인으로 연결 -> 매칭된 것만 최신순 반환."""
        stream: Iterable[Transaction] = self.txs.stream()
        stream = _filter(stream, date_from, date_to, category, type, q, tag)
        return sorted(stream, key=_newest_key, reverse=True)  # 조건에 맞는 것만 모아 정렬

    # --- 요약 / 예산 ---
    def summary(self, month: str) -> Summary:
        check_date(month, "%Y-%m")
        s = Summary(month=month)
        by_cat: dict[str, int] = defaultdict(int)
        for t in self.txs.stream():
            if not t.date.startswith(month + "-"):
                continue
            s.count += 1
            if t.type == "income":
                s.income += t.amount
            else:
                s.expense += t.amount
                by_cat[t.category] += t.amount
        s.by_category = dict(by_cat)
        budget = self.budgets.get(month)
        s.budget = budget.amount if budget else None
        return s

    def set_budget(self, month: str, amount: int) -> Budget:
        check_date(month, "%Y-%m")
        budget = Budget(month=month, amount=parse_amount(amount))
        self.budgets.set(budget)
        return budget

    # --- CSV import / export ---
    def import_csv(self, path: Path) -> tuple[int, int, list[str]]:
        """CSV 행을 하나씩 검증 후 저장. (imported, skipped, 오류메시지들)"""
        if not path.exists():
            raise AppError(f"파일이 없습니다: {path}", "경로를 확인하세요.")
        imported, skipped, errors = 0, 0, []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = {"date", "type", "category", "amount"} - set(reader.fieldnames or [])
            if missing:
                raise AppError(f"CSV 필수 컬럼 누락: {', '.join(sorted(missing))}",
                               f"헤더 예: {','.join(CSV_COLUMNS)}")
            for line_no, row in enumerate(reader, start=2):
                try:
                    self.add(
                        type=(row["type"] or "").strip(),
                        date=check_date((row["date"] or "").strip()),
                        amount=parse_amount((row["amount"] or "").strip()),
                        category=(row["category"] or "").strip(),
                        memo=(row.get("memo") or "").strip(),
                        tags=parse_tags(row.get("tags")),
                    )
                    imported += 1
                except (AppError, ValueError) as e:
                    skipped += 1
                    errors.append(f"{line_no}행: {getattr(e, 'message', e)}")
        return imported, skipped, errors

    def export_csv(self, out: Path, month: str | None = None,
                   date_from: str | None = None, date_to: str | None = None) -> int:
        if not (month or date_from or date_to):
            raise AppError("export 조건이 없습니다.",
                           "--month YYYY-MM 또는 --from/--to YYYY-MM-DD 중 하나 이상 지정하세요.")
        if month:
            check_date(month, "%Y-%m")
        stream = _filter(self.txs.stream(), date_from, date_to)
        if month:
            stream = (t for t in stream if t.date.startswith(month + "-"))

        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            for t in stream:  # 한 건씩 흘려서 바로 기록
                writer.writerow([t.date, t.type, t.category, t.amount, t.memo, ",".join(t.tags)])
                count += 1
        return count


def _newest_key(t: Transaction) -> tuple[str, str]:
    """최신순 정렬 기준: (날짜, id). id는 TX-000001 형식이라 문자열 비교 = 등록 순서"""
    return (t.date, t.id)


def _filter(stream: Iterable[Transaction], date_from: str | None = None,
            date_to: str | None = None, category: str | None = None,
            type: str | None = None, q: str | None = None,
            tag: str | None = None) -> Iterator[Transaction]:
    """조건마다 제너레이터를 한 겹씩 씌운다. 아무것도 메모리에 쌓지 않음.

    (이 함수 자체는 일반 함수라 날짜/type 검증은 호출 즉시 일어난다.)
    """
    if date_from:
        check_date(date_from)
        stream = (t for t in stream if t.date >= date_from)  # YYYY-MM-DD는 문자열 비교 = 날짜 비교
    if date_to:
        check_date(date_to)
        stream = (t for t in stream if t.date <= date_to)
    if category:
        stream = (t for t in stream if t.category == category)
    if type:
        if type not in ("income", "expense"):
            raise AppError(f"허용되지 않은 type: {type!r}", "income 또는 expense")
        stream = (t for t in stream if t.type == type)
    if q:
        stream = (t for t in stream if q.lower() in t.memo.lower())
    if tag:
        stream = (t for t in stream if tag in t.tags)
    return iter(stream)
