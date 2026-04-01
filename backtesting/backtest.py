"""기본 백테스터.

market_data.db 축적 데이터로 실데이터 리플레이.
수수료 + 슬리피지 반영. 전략별/국면별/Tier별 성과 분리.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from market.impact_model import estimate_slippage

logger = logging.getLogger(__name__)

FEE_RATE = 0.0025  # 편도 0.25%


@dataclass
class BacktestResult:
    """백테스트 결과."""

    total_trades: int = 0
    win_count: int = 0
    total_pnl: float = 0.0
    gross_pnl: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    equity_curve: list[float] = field(default_factory=list)


@dataclass
class Trade:
    """백테스트 거래."""

    entry_price: float
    exit_price: float
    qty: float
    fee: float = 0.0
    pnl: float = 0.0


class Backtester:
    """기본 백테스터."""

    def __init__(
        self,
        slippage_pct: float = 0.001,
        fee_rate: float = FEE_RATE,
    ) -> None:
        """초기화.

        Args:
            slippage_pct: 고정 슬리피지 비율 (편도). adv_krw 미제공 시 사용.
            fee_rate: 수수료 비율 (편도).
        """
        self._slippage = slippage_pct
        self._fee_rate = fee_rate

    def run(
        self,
        trades: list[dict],
        initial_equity: float = 1_000_000,
    ) -> BacktestResult:
        """거래 리스트로 백테스트를 실행한다.

        Args:
            trades: 거래 리스트. 각 항목: {"entry_price", "exit_price", "qty"}.
            initial_equity: 초기 자본.

        Returns:
            BacktestResult.
        """
        if not trades:
            return BacktestResult()

        equity = initial_equity
        peak = initial_equity
        max_dd = 0.0
        returns: list[float] = []
        wins = 0
        losses_sum = 0.0
        wins_sum = 0.0
        total_fees = 0.0
        equity_curve = [equity]

        for t in trades:
            entry = t["entry_price"]
            exit_p = t["exit_price"]
            qty = t.get("qty", 1.0)

            # 슬리피지 적용 (√(Q/V) 임팩트 모델 또는 고정)
            adv = t.get("adv_krw", 0)
            vol = t.get("volatility", 0)
            order_krw = entry * qty
            if adv > 0:
                slip = estimate_slippage(order_krw, adv, vol if vol > 0 else 0.03)
            else:
                slip = self._slippage
            entry_adj = entry * (1 + slip)
            exit_adj = exit_p * (1 - slip)

            # 수수료
            entry_fee = entry_adj * qty * self._fee_rate
            exit_fee = exit_adj * qty * self._fee_rate
            fee = entry_fee + exit_fee
            total_fees += fee

            # PnL
            gross = (exit_adj - entry_adj) * qty
            net = gross - fee

            equity += net
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

            ret = net / (entry_adj * qty) if entry_adj * qty > 0 else 0
            returns.append(ret)

            if net > 0:
                wins += 1
                wins_sum += net
            else:
                losses_sum += abs(net)

            equity_curve.append(equity)

        n = len(trades)
        total_pnl = equity - initial_equity
        expectancy = total_pnl / n if n > 0 else 0
        win_rate = wins / n if n > 0 else 0
        pf = wins_sum / losses_sum if losses_sum > 0 else 10.0

        # Sharpe
        if returns:
            arr = np.array(returns)
            mean_r = float(np.mean(arr))
            std_r = float(np.std(arr))
            sharpe = mean_r / std_r * np.sqrt(252) if std_r > 0 else 0
        else:
            sharpe = 0

        return BacktestResult(
            total_trades=n,
            win_count=wins,
            total_pnl=total_pnl,
            gross_pnl=total_pnl + total_fees,
            total_fees=total_fees,
            max_drawdown=max_dd,
            sharpe=sharpe,
            expectancy=expectancy,
            profit_factor=pf,
            win_rate=win_rate,
            equity_curve=equity_curve,
        )
