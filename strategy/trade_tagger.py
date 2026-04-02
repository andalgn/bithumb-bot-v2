"""TradeTagger — 거래 결과를 실패 유형으로 분류한다."""

from __future__ import annotations

from typing import Literal

TradeTag = Literal[
    "regime_mismatch",  # 진입 국면 ≠ 청산 국면 (시장 급변)
    "timing_error",  # 방향은 맞지만 SL 먼저 도달 (진입 타이밍 오류)
    "sizing_error",  # 수익 < 수수료 (포지션 너무 작음)
    "signal_quality",  # 방향 자체가 틀림 (신호 품질 불량)
    "external",  # 거래소 오류, API 실패, 최소 주문금액
    "winner",  # 수익 거래 (분류 불필요)
]

_EXTERNAL_KEYWORDS = ("api", "error", "timeout", "minimum", "reconcil")
_SL_KEYWORDS = ("sl", "stop_loss")


def tag_trade(
    trade: dict,
    entry_regime: str | None = None,
    exit_regime: str | None = None,
) -> TradeTag:
    """거래 결과를 실패 유형으로 분류한다.

    우선순위 순서로 평가한다:
    1. winner — 순수익 > 0
    2. external — 외부 오류(API, 타임아웃, 최소주문금액 등)
    3. regime_mismatch — 진입/청산 국면 불일치
    4. timing_error — SL 청산이지만 가격 방향은 올바름
    5. sizing_error — 손실이 수수료보다 작음 (포지션 크기 과소)
    6. signal_quality — 그 외 모든 손실 (기본값)

    Args:
        trade: journal.get_recent_trades() 반환 dict.
            필드: net_pnl_krw, exit_reason, entry_price, exit_price,
                  qty, regime, entry_fee_krw, exit_fee_krw 등.
        entry_regime: 진입 시 국면 문자열 (없으면 trade['regime'] 사용).
        exit_regime: 청산 시 국면 문자열 (없으면 None으로 처리).

    Returns:
        TradeTag 문자열.
    """
    net_pnl: float = trade.get("net_pnl_krw", 0) or 0
    exit_reason: str = (trade.get("exit_reason") or "").lower()

    # 1. winner
    if net_pnl > 0:
        return "winner"

    # 2. external
    if any(kw in exit_reason for kw in _EXTERNAL_KEYWORDS):
        return "external"

    # 3. regime_mismatch
    _entry_regime = entry_regime or trade.get("regime")
    _exit_regime = exit_regime
    if _entry_regime is not None and _exit_regime is not None and _entry_regime != _exit_regime:
        return "regime_mismatch"

    # 4. timing_error: SL 청산이고, 가격이 실제로 진입가보다 높은 상태에서 손절됨
    #    (롱 포지션 기준: exit_price > entry_price 인데 net_pnl < 0 → 슬리피지/타이밍)
    if any(kw in exit_reason for kw in _SL_KEYWORDS) and net_pnl < 0:
        entry_price: float = trade.get("entry_price", 0) or 0
        exit_price_val: float = trade.get("exit_price", 0) or 0
        if entry_price > 0 and exit_price_val > entry_price:
            return "timing_error"

    # 5. sizing_error: 손실이 수수료보다 작으면 포지션이 너무 작았음
    entry_fee: float = trade.get("entry_fee_krw", 0) or 0
    exit_fee: float = trade.get("exit_fee_krw", 0) or 0
    total_fee: float = entry_fee + exit_fee

    if total_fee == 0:
        # fee 정보가 없으면 추정: 매수+매도 합산 0.5%
        ep: float = trade.get("entry_price", 0) or 0
        qty: float = trade.get("qty", 0) or 0
        total_fee = ep * qty * 0.005

    if net_pnl < 0 and abs(net_pnl) < total_fee:
        return "sizing_error"

    # 6. signal_quality — 기본값
    return "signal_quality"
