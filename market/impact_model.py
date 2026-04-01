"""Square-Root Impact 거래비용 모델.

Almgren-Chriss 프레임워크 기반 비선형 슬리피지 추정.
논문: Tóth et al. (2011), Almgren & Chriss (2001)

공식: slippage = Y × σ × √(Q / V)
- Y: 임팩트 계수 (기본 0.5, 보수적 추정)
- σ: 일일 변동성 (수익률 표준편차)
- Q: 주문 금액 (KRW)
- V: 일평균 거래대금 (KRW)
"""

from __future__ import annotations

import math

# 임팩트 계수 (empirical prefactor)
# 0.5~1.0 범위 (Tóth et al.), 보수적으로 0.5 사용
IMPACT_Y = 0.5

# 슬리피지 하한/상한 (편도)
MIN_SLIPPAGE = 0.0001  # 0.01%
MAX_SLIPPAGE = 0.0200  # 2.0%

# 기본 일일 변동성 (데이터 미제공 시)
DEFAULT_VOLATILITY = 0.03  # 3%


def estimate_slippage(
    order_krw: float,
    adv_krw: float,
    volatility: float = DEFAULT_VOLATILITY,
    impact_y: float = IMPACT_Y,
) -> float:
    """Square-Root Impact Law 기반 슬리피지를 추정한다.

    Args:
        order_krw: 주문 금액 (KRW).
        adv_krw: 일평균 거래대금 (KRW).
        volatility: 일일 수익률 변동성 (σ).
        impact_y: 임팩트 계수 (Y).

    Returns:
        편도 슬리피지 비율 (0.0001 ~ 0.02).
    """
    if order_krw <= 0 or adv_krw <= 0:
        return MIN_SLIPPAGE

    participation = order_krw / adv_krw
    slippage = impact_y * volatility * math.sqrt(participation)

    return max(MIN_SLIPPAGE, min(slippage, MAX_SLIPPAGE))
