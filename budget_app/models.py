'''
@dataclass : __init__, __repr__, __eq__ 를 자도 생성함. -> 보일러플레이트 제거
타입힌트 = 계약 : amount: int, type: Literal[..] -> 뭘 주고받는지 명시, 파이썬이 강제하진 않지만 문서 + 검증 기준
field(default_factory=list): tags: list=[] 쓰면 모든 인스턴스가 같은 리스트 공유한다.
__post_init__: dataclass가 만든 __init__ 직후 자동 호출 -> 검증 자리. "모델이 스스로 유효성 보장"
'''

# 모델 계층 - 순수 데이터 + 자기 검증 구조
# 이 계층은 '무읏을 담는가'만 다룬다.

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal

# type 필드는 이 두 값만 허용 - 타입힌트 자체가 계약서 역할
TxType = Literal["income", "expense"] # type 필드 계약을 상수로 분리

@dataclass # --> print(t) 하면 필드 다 보이게함
class Transaction:
    id: str
    type: TxType    # "income" | "expense"
    date: str       # YYYY-MM-DD
    amount: int     # 양수 - 정수
    category: str   
    memo: str = ""  # 선택 
    tags: list[str] = field(default_factory=list)   # 선택 (mutable -> default_factory) 
    # 인스턴스마다 새 빈리스트

    # __init__ 직후 자동 실행 -> 잘못된 데이터는 여기서 걸러짐
    def __post_init__(self) -> None:  # 생성 직후 자동 검증
        if self.type not in ("income", "expense"):
            raise ValueError(f"type은 income/expense만 가능: {self.type!r}")
        try:
            datetime.strptime(self.date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"날짜 형식 오류(YYYY-MM-DD): {self.date!r}")
        if self.amount <= 0:
            raise ValueError(f"금액은 양수여야 함: {self.amount}")

    def to_dict(self) -> dict: # 객체 ↔ dict 변환
        """JSONL 한줄(dict)로 변환 -- 저장용."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        """저장된 dict -> Transactino 복원. 검증은 __post_init__이 자동 수행"""
        return cls(
            id=d["id"],
            type=d["type"],
            date=d["date"],
            amount=int(d["amount"]),
            category=d["category"],
            memo=d.get("memo", ""),
            tags=list(d.get("tags", [])),
        )

@dataclass
class Budget:
    month: str  # YYYY-MM
    amount: int # 양수 - 정수

    def __post_init__(self) -> None:
        try:
            datetime.strptime(self.month, "%Y-%m")
        except ValueError:
            raise ValueError(f"월 형식 오류(YYYY-MM): {self.month!r}")
        if self.amount <= 0:
            raise ValueError(f"예산은 양수여야함: {self.amount}")
    def to_dict(self) -> dict:
        return asdict(self)


    @classmethod # dict로 객체 만드는 "대안 생성자"
    def from_dict(cls, d: dict) -> "Budget": # 객체 ↔ dict 변환
        return cls(month=d["month"], amount=int(d["amount"])) 



# 결론 : models.py 는 "데이터가 무엇인지 + 데이터가 항상 유효하도록" . 이 두가지만 책임진다. 저장과 계산 방법은 모른다.
# to_dict(내보내기) ↔ from_dict(들여오기) 가 짝이다. storage가 정확히 이 두개만 호출해서 파일을 다룰 것임.