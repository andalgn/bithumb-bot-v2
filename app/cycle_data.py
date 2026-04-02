"""사이클 내 공유 데이터 컨테이너.

run_cycle() 분해 후 각 메서드 간 데이터 전달에 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data_types import Regime


@dataclass
class MarketData:
    """한 사이클에서 수집·계산된 시장 데이터."""

    snapshots: dict = field(default_factory=dict)
    """symbol → MarketSnapshot"""

    current_prices: dict[str, float] = field(default_factory=dict)
    """symbol → 현재가"""

    indicators_1h: dict = field(default_factory=dict)
    """symbol → IndicatorPack (1H)"""

    regimes: dict[str, Regime] = field(default_factory=dict)
    """symbol → Regime"""
