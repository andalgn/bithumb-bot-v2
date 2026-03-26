"""TradeTagger 단위 테스트."""
from __future__ import annotations

import pytest

from strategy.trade_tagger import TradeTag, tag_trade


def _make_trade(**kwargs) -> dict:
    """기본 거래 dict를 생성한다.

    trades 테이블 필드 기준: net_pnl_krw, exit_reason, entry_price,
    exit_price, qty, regime, entry_fee_krw, exit_fee_krw.
    """
    defaults = {
        "net_pnl_krw": -5000,
        "exit_reason": "stop_loss",
        "entry_price": 100000,
        "exit_price": 98000,
        "qty": 0.01,
        "regime": "RANGE",
        "entry_fee_krw": 400,
        "exit_fee_krw": 400,
    }
    defaults.update(kwargs)
    return defaults


# ── 1. winner ────────────────────────────────────────────────────────────────

def test_winner_tagged_correctly() -> None:
    """순수익 > 0 이면 winner로 분류된다."""
    trade = _make_trade(net_pnl_krw=3000)
    assert tag_trade(trade) == "winner"


def test_winner_zero_pnl_is_not_winner() -> None:
    """순수익 == 0 이면 winner가 아니다."""
    trade = _make_trade(net_pnl_krw=0, exit_reason="tp")
    result = tag_trade(trade)
    assert result != "winner"


# ── 2. external ──────────────────────────────────────────────────────────────

def test_external_tagged_on_api_error() -> None:
    """exit_reason에 'api' 포함 시 external로 분류된다."""
    trade = _make_trade(net_pnl_krw=-1000, exit_reason="api_timeout")
    assert tag_trade(trade) == "external"


def test_external_tagged_on_timeout() -> None:
    """exit_reason에 'timeout' 포함 시 external로 분류된다."""
    trade = _make_trade(net_pnl_krw=-500, exit_reason="timeout")
    assert tag_trade(trade) == "external"


def test_external_tagged_on_minimum() -> None:
    """exit_reason에 'minimum' 포함 시 external로 분류된다."""
    trade = _make_trade(net_pnl_krw=-200, exit_reason="minimum_order")
    assert tag_trade(trade) == "external"


def test_external_tagged_on_reconcil() -> None:
    """exit_reason에 'reconcil' 포함 시 external로 분류된다."""
    trade = _make_trade(net_pnl_krw=-100, exit_reason="reconciliation")
    assert tag_trade(trade) == "external"


def test_external_tagged_on_error() -> None:
    """exit_reason에 'error' 포함 시 external로 분류된다."""
    trade = _make_trade(net_pnl_krw=-300, exit_reason="order_error")
    assert tag_trade(trade) == "external"


# ── 3. regime_mismatch ───────────────────────────────────────────────────────

def test_regime_mismatch_tagged() -> None:
    """진입/청산 국면이 다르면 regime_mismatch로 분류된다."""
    trade = _make_trade(net_pnl_krw=-2000, exit_reason="sl")
    assert tag_trade(trade, entry_regime="STRONG_UP", exit_regime="WEAK_DOWN") == "regime_mismatch"


def test_regime_mismatch_requires_both_regimes() -> None:
    """exit_regime이 None이면 regime_mismatch로 분류되지 않는다."""
    trade = _make_trade(net_pnl_krw=-2000, exit_reason="sl")
    result = tag_trade(trade, entry_regime="STRONG_UP", exit_regime=None)
    assert result != "regime_mismatch"


def test_regime_same_no_mismatch() -> None:
    """진입/청산 국면이 동일하면 regime_mismatch가 아니다."""
    trade = _make_trade(net_pnl_krw=-2000, exit_reason="sl")
    result = tag_trade(trade, entry_regime="RANGE", exit_regime="RANGE")
    assert result != "regime_mismatch"


# ── 4. sizing_error ───────────────────────────────────────────────────────────

def test_sizing_error_when_loss_smaller_than_fee() -> None:
    """손실이 수수료보다 작으면 sizing_error로 분류된다."""
    trade = _make_trade(net_pnl_krw=-300, entry_fee_krw=400, exit_fee_krw=400, exit_reason="tp")
    assert tag_trade(trade) == "sizing_error"


def test_sizing_error_with_zero_fee_uses_estimate() -> None:
    """fee 필드가 0 이면 추정 수수료(0.5%)를 사용한다."""
    # entry_price=100000, qty=0.1 → fee_estimate = 100000 * 0.1 * 0.005 = 50
    # net_pnl=-10 < 0 and abs(-10) < 50 → sizing_error
    trade = _make_trade(
        net_pnl_krw=-10,
        entry_fee_krw=0,
        exit_fee_krw=0,
        entry_price=100000,
        qty=0.1,
        exit_reason="tp",
    )
    assert tag_trade(trade) == "sizing_error"


def test_sizing_error_not_triggered_when_loss_exceeds_fee() -> None:
    """손실이 수수료보다 크면 sizing_error가 아니다."""
    trade = _make_trade(net_pnl_krw=-5000, entry_fee_krw=400, exit_fee_krw=400, exit_reason="sl")
    result = tag_trade(trade)
    assert result != "sizing_error"


# ── 5. timing_error ───────────────────────────────────────────────────────────

def test_timing_error_sl_but_price_above_entry() -> None:
    """SL 청산이지만 exit_price > entry_price 이면 timing_error로 분류된다.

    (롱 포지션에서 가격은 올랐지만 손절 — 슬리피지 또는 타이밍 문제)
    """
    trade = _make_trade(
        net_pnl_krw=-200,
        exit_reason="sl",
        entry_price=100000,
        exit_price=101000,  # 가격은 올랐음
        entry_fee_krw=400,
        exit_fee_krw=400,
    )
    assert tag_trade(trade) == "timing_error"


def test_timing_error_stop_loss_keyword() -> None:
    """exit_reason이 'stop_loss' 키워드를 포함해도 timing_error가 적용된다."""
    trade = _make_trade(
        net_pnl_krw=-200,
        exit_reason="stop_loss",
        entry_price=100000,
        exit_price=102000,
        entry_fee_krw=400,
        exit_fee_krw=400,
    )
    assert tag_trade(trade) == "timing_error"


def test_timing_error_not_triggered_when_price_below_entry() -> None:
    """exit_price < entry_price 이면 timing_error가 아닌 signal_quality."""
    trade = _make_trade(
        net_pnl_krw=-5000,
        exit_reason="sl",
        entry_price=100000,
        exit_price=95000,
        entry_fee_krw=400,
        exit_fee_krw=400,
    )
    assert tag_trade(trade) == "signal_quality"


# ── 6. signal_quality ────────────────────────────────────────────────────────

def test_signal_quality_default() -> None:
    """그 외 손실 거래는 signal_quality로 분류된다."""
    trade = _make_trade(net_pnl_krw=-5000, exit_reason="stop_loss")
    assert tag_trade(trade, entry_regime="RANGE", exit_regime="RANGE") == "signal_quality"


def test_signal_quality_regime_change_exit() -> None:
    """REGIME 청산이지만 국면 정보 없을 경우 signal_quality."""
    trade = _make_trade(net_pnl_krw=-3000, exit_reason="regime")
    assert tag_trade(trade) == "signal_quality"


# ── 7. priority order ────────────────────────────────────────────────────────

def test_winner_takes_priority_over_external() -> None:
    """winner가 external보다 우선한다."""
    trade = _make_trade(net_pnl_krw=500, exit_reason="api_error")
    assert tag_trade(trade) == "winner"


def test_external_takes_priority_over_regime_mismatch() -> None:
    """external이 regime_mismatch보다 우선한다."""
    trade = _make_trade(net_pnl_krw=-1000, exit_reason="api_error")
    assert tag_trade(trade, entry_regime="STRONG_UP", exit_regime="CRISIS") == "external"
