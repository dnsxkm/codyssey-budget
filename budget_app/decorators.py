""" 공통 관심사 계층 - 예외 처리 / 실행 로그 / 시간 측정

비즈니스 로직 안에 try/except, print(로그), time 측정을 섞지 않고
데코레이터로 '바깥에서 감싸서' 분리한다.
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from typing import Callable, TypeVar

from budget_app.errors import AppError

logger = logging.getLogger("budget_app")

F = TypeVar("F", bound=Callable[..., int])


def handle_errors(func: F) -> F:
    """예외를 잡아 스택트레이스 대신 '원인 + 힌트'를 출력하고 종료 코드(int)를 돌려준다.

    정상 -> 함수가 반환한 코드(보통 0), 오류 -> 0이 아닌 값
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> int:
        try:
            return func(*args, **kwargs)
        except AppError as e:
            _print_error(e.message, e.hint)
            return 1
        except ValueError as e:  # 모델 __post_init__ 검증 실패 등
            _print_error(str(e), "입력 값을 확인하세요. --help 로 사용법을 볼 수 있습니다.")
            return 1
        except OSError as e:  # 파일 없음 / 권한 등
            _print_error(f"파일 처리 실패: {e.strerror} ({e.filename})", "경로와 권한을 확인하세요.")
            return 2
        except (KeyboardInterrupt, EOFError):
            print("\n[취소] 입력이 중단되었습니다.", file=sys.stderr)
            return 130
        except Exception as e:  # 최후의 안전망: 어떤 경우에도 스택트레이스는 보이지 않는다
            _print_error(f"예상치 못한 오류: {type(e).__name__}: {e}", "--verbose 로 다시 실행해 로그를 확인하세요.")
            return 1

    return wrapper  # type: ignore[return-value]


def log_call(func: F) -> F:
    """명령 실행 시작/종료를 로그로 남긴다 (--verbose 일 때 보임)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> int:
        logger.info("실행 시작: %s", func.__name__)
        code = func(*args, **kwargs)
        logger.info("실행 종료: %s (exit=%s)", func.__name__, code)
        return code

    return wrapper  # type: ignore[return-value]


def timed(func: F) -> F:
    """실행 시간 측정 (--verbose 일 때 보임)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> int:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            logger.info("%s 소요시간: %.3fs", func.__name__, time.perf_counter() - start)

    return wrapper  # type: ignore[return-value]


def _print_error(message: str, hint: str) -> None:
    print(f"[오류] {message}", file=sys.stderr)
    if hint:
        print(f"[힌트] {hint}", file=sys.stderr)
