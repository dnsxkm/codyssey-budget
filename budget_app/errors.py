"""공통 예외 - 사용자에게 보여줄 '원인 + 해결 힌트'를 담는다."""

from __future__ import annotations


class AppError(Exception):
    """예상 가능한 오류. 데코레이터가 잡아서 [오류]/[힌트]로 출력한다."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
