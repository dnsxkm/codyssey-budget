""" 저장소 계층 - 파일 Input / Output 전담 (JSONL) 

읽기는 제너레이터 스트리밍, update/delete 쓰기는 원자적 교체
'어디에/어떻게 저장하냐'만 다룬다. 비즈니스 규칙은 services가 담당

"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator

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
        for line in f:  # 파일 객체 전체가 '줄 단위 이터레이터'
            line = line.strip()
            if not line :   # 빈 줄은 건너뛰기
                continue
            yield json.loads(line)

def _atomic_write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    """ 임시 파일에 전부 쓴 뒤 원자적으로 교체한다.
    
    쓰다가 프로그램이 죽어도 원본(path)은 손대지 않은 상태로 남는다.
    """

    path.parent.mkdir(parents=True, exist_ok=True) # data 폴더 보장
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascli=False) + "\n") 
        f.flush()
        os.fsync(f.fileno()) # OS 버퍼까지 디스크에 강제 기록
    os.replace(tmp, path) # 교체



# ---------- 거래 저장소 ---------- 
class TransactionRepository:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "transactions.jsonl"

    def stream(self) -> Iterator[Transaction]:
        """저장 순서(오래된 -> 최신)대로 한 건씩 스트리밍"""
        for d in _iter_jsonl(self.path):
            yield Transaction.from_dict(d)

    def append(self, tx: Transaction) -> None:
        """맨 뒤에 한 줄 추가. 전체 재작성 불필요 -> 빠름"""
        self.path.parent.mkdir(parents=True, exist_ok = True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tx.to_dict(), ensure_ascli=False) + "\n") 

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
