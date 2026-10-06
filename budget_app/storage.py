""" 저장소 계층 - 파일 Input / Output 전담 (JSONL) 

읽기는 제너레이터 스트리밍, update/delete 쓰기는 원자적 교체
'어디에/어떻게 저장하냐'만 다룬다. 비즈니스 규칙은 services가 담당

"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator

from budget_app.errors import AppError
from budget_app.models import Transaction, Budget

# 카테고리 파일이 없을 때 자동 생성할 기본값 
DEFAULT_CATEGORIES = ["food", "transport", "rent", "salary", "etc"]

# ---------- 공통 헬퍼 ( 모듈 내부용 ) ---------- 
def _iter_jsonl(path: Path) -> Iterator[dict]:
    """파일을 '한줄씩' 읽어 dict로 흘려보내는 제너레이터
    
    핵심: 전체 내용을 메모리에 올리지 않고, 한 줄 읽고 -> yield -> 다음 줄.
    파일이 없으면 아무것도 내보내지 않는다 (빈 스트림)
    """

    if not path.exists():
        return 
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):  # 파일 객체 전체가 '줄 단위 이터레이터'
            line = line.strip()
            if not line :   # 빈 줄은 건너뛰기
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                raise _corrupt(path, line_no)

def _atomic_write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    """ 임시 파일에 전부 쓴 뒤 원자적으로 교체한다.
    
    쓰다가 프로그램이 죽어도 원본(path)은 손대지 않은 상태로 남는다.
    """

    path.parent.mkdir(parents=True, exist_ok=True) # data 폴더 보장
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno()) # OS 버퍼까지 디스크에 강제 기록
    except BaseException:
        tmp.unlink(missing_ok=True) # 검증 실패 등으로 중단되면 임시 파일 정리 (원본은 그대로)
        raise
    os.replace(tmp, path) # 교체



def _corrupt(path: Path, n: int) -> AppError:
    return AppError(f"데이터 파일이 손상되었습니다: {path} ({n}번째 레코드)",
                    "해당 줄을 직접 고치거나 삭제한 뒤 다시 실행하세요.")


# ---------- 거래 저장소 ---------- 
class TransactionRepository:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "transactions.jsonl"

    def stream(self) -> Iterator[Transaction]:
        """저장 순서(오래된 -> 최신)대로 한 건씩 스트리밍"""
        for n, d in enumerate(_iter_jsonl(self.path), start=1):
            try:
                tx = Transaction.from_dict(d)
            except (KeyError, TypeError, ValueError):
                raise _corrupt(self.path, n)
            yield tx

    def append(self, tx: Transaction) -> None:
        """맨 뒤에 한 줄 추가. 전체 재작성 불필요 -> 빠름"""
        self.path.parent.mkdir(parents=True, exist_ok = True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tx.to_dict(), ensure_ascii=False) + "\n") 

    def delete(self, tx_id: str) -> bool:
        """ id 일치하는 것만 빼고 전부 다시 씀(원자적). 실제로 지웠다면 True 반환"""
        found = False

        def kept() -> Iterator[dict]:
            nonlocal found
            for d in _iter_jsonl(self.path):
                if d["id"] == tx_id:
                    found = True
                    continue    

                yield d

        _atomic_write_jsonl(self.path, kept())
        return found
    
    def update(self, tx_id: str, changes: dict) -> bool:
        """id 찾아 changes 병합 후, 전체 재작성. 찾았으면 True"""
        found = False
        def updated() -> Iterator[dict]:
            nonlocal found

            for d in _iter_jsonl(self.path):
                if d["id"] == tx_id:
                    found = True
                    d = {**d, **changes} # 기존 위에 변경분 덮기
                    Transaction.from_dict(d) # 검증: 잘못된 수정이면 여기서 걸린다.
                yield d
        _atomic_write_jsonl(self.path, updated())
        return found

    def next_id(self) -> str :
        """가장 큰 번호 + 1. 스트리밍으로 흝으며 최대값만 기억"""
        max_n = 0
        for d in _iter_jsonl(self.path) :
            try:
                n = int(str(d["id"]).split("-")[1])
            except (IndexError, ValueError) :
                continue
            max_n = max(max_n, n)

        return f"TX-{max_n + 1:06d}"

# ---------- 카테고리 저장소 ----------

class CategoryStore :
    def __init__(self, data_dir: Path) -> None :
        self.path = data_dir / "categories.jsonl"
        if not self.list() :
            self._seed() # 파일이 없거나 비어 있으면 기본 카테고리 자동 생성

    def _seed(self) -> None :
        _atomic_write_jsonl(self.path, ({"name": c} for c in DEFAULT_CATEGORIES))

    def list(self) -> list[str] :
        return [d["name"] for d in _iter_jsonl(self.path)]

    def add(self, name: str) -> bool :
        """이미 있으면 False, 새로 추가하면 True"""
        if name in self.list() :
            return False
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"name": name}, ensure_ascii=False) + "\n")
        return True

    def remove(self, name: str) -> bool :
        """순수 삭제만. '사용 중이면 막기'는 서비스 계층 책임."""
        cats = self.list()
        if name not in cats:
            return False
        _atomic_write_jsonl(self.path, ({"name": c} for c in cats if c != name))

        return True

# ---------- 예산 저장소 ----------

class BudgetStore :
    def __init__(self, data_dir: Path) -> None :
        self.path = data_dir / "budgets.jsonl"

    def get(self, month: str) -> Budget | None :
        for d in _iter_jsonl(self.path) :
            if d["month"] == month :
                return Budget.from_dict(d)

        return None

    def set(self, budget: Budget) -> None :
        """같은 month 있으면 교체, 없으면 추가(upsert). 원자적 재작성"""
        replaced = False

        def rows() -> Iterator[dict] :
            nonlocal replaced
            for d in _iter_jsonl(self.path) :
                if d["month"] == budget.month :
                    replaced = True
                    yield budget.to_dict() # 기존 월 -> 새 값으로 교체
                else : 
                    yield d

            if not replaced :
                yield budget.to_dict()  # 없던 월이면 끝에 추가

        _atomic_write_jsonl(self.path, rows())



