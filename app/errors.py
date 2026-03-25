"""커스텀 예외 계층.

BotError를 최상위로, 원인별 구체적 예외 타입을 정의한다.
각 예외 타입에 따른 복구 동작:
  - InsufficientBalanceError: 주문 취소 + Discord 알림
  - OrderTimeoutError: 취소 후 다음 사이클 재시도
  - DataFetchError: 캐시 사용 또는 사이클 스킵
  - PositionLimitExceededError: 진입 거부 (로그만)
  - APIAuthError: 봇 일시정지 + Discord 알림
"""
from __future__ import annotations


class BotError(Exception):
    """모든 봇 예외의 최상위 클래스."""


class InsufficientBalanceError(BotError):
    """잔고 부족으로 주문 불가.

    복구: 주문 취소 + 알림.
    """

    def __init__(self, symbol: str, required: float, available: float) -> None:
        super().__init__(
            f"{symbol}: 잔고 부족 (필요={required:,.0f}원, 가용={available:,.0f}원)"
        )
        self.symbol = symbol
        self.required = required
        self.available = available


class OrderTimeoutError(BotError):
    """주문이 제한 시간 내 체결되지 않음.

    복구: 취소 후 다음 사이클 재시도.
    """

    def __init__(self, ticket_id: str, reason: str = "") -> None:
        super().__init__(f"주문 타임아웃: {ticket_id}" + (f" — {reason}" if reason else ""))
        self.ticket_id = ticket_id


class DataFetchError(BotError):
    """시장 데이터 조회 실패.

    복구: 캐시된 데이터 사용 또는 해당 코인 사이클 스킵.
    """

    def __init__(self, symbol: str, reason: str = "") -> None:
        super().__init__(f"{symbol}: 데이터 조회 실패" + (f" — {reason}" if reason else ""))
        self.symbol = symbol
        self.reason = reason


class PositionLimitExceededError(BotError):
    """포지션 한도 초과로 진입 불가.

    복구: 진입 거부 (로그만).
    """

    def __init__(self, symbol: str, current: int, limit: int) -> None:
        super().__init__(f"{symbol}: 포지션 한도 초과 ({current}/{limit})")
        self.symbol = symbol
        self.current = current
        self.limit = limit


class APIAuthError(BotError):
    """API 인증 실패.

    복구: 봇 일시정지 + Discord 알림.
    """

    def __init__(self, reason: str = "") -> None:
        super().__init__(f"API 인증 실패" + (f": {reason}" if reason else ""))
