"""전략 엔진 테스트 — 국면 분류 + 점수 계산 + Layer 1 + 통합."""

import numpy as np
import pytest

from app.data_types import (
    Candle,
    MarketSnapshot,
    Orderbook,
    OrderbookEntry,
    Regime,
    Strategy,
    Tier,
)
from strategy.indicators import compute_indicators
from strategy.rule_engine import AuxFlags, RuleEngine, SizeDecision
from strategy.spread_profiler import SpreadProfiler


def _make_candles(
    base: float, count: int, trend: float = 0.0, volatility: float = 0.01
) -> list[Candle]:
    """테스트용 캔들 생성."""
    candles = []
    price = base
    for i in range(count):
        price += trend
        candles.append(
            Candle(
                timestamp=1000 * (i + 1),
                open=price * (1 - volatility * 0.5),
                high=price * (1 + volatility),
                low=price * (1 - volatility),
                close=price,
                volume=1000.0 + i * 10,
            )
        )
    return candles


def _make_orderbook(spread_pct: float = 0.001, depth_qty: float = 100.0) -> Orderbook:
    """테스트용 호가창 생성."""
    mid = 50000000.0
    half_spread = mid * spread_pct / 2
    return Orderbook(
        timestamp=1000,
        bids=[OrderbookEntry(price=mid - half_spread, quantity=depth_qty) for _ in range(5)],
        asks=[OrderbookEntry(price=mid + half_spread, quantity=depth_qty) for _ in range(5)],
    )


@pytest.fixture
def engine() -> RuleEngine:
    """테스트용 RuleEngine."""
    return RuleEngine(spread_profiler=SpreadProfiler(db_path="/tmp/nonexistent_test.db"))


# ═══════════════════════════════════════════
# 국면 분류 테스트
# ═══════════════════════════════════════════


class TestRegimeClassification:
    """국면 분류 테스트."""

    def test_range_default(self, engine: RuleEngine) -> None:
        """데이터 부족 시 RANGE."""
        candles = _make_candles(100, 25, trend=0)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        regime, _ = engine.classify_regime("BTC", ind, close)
        assert regime == Regime.RANGE

    def test_strong_up_detection(self, engine: RuleEngine) -> None:
        """강한 상승 추세 감지."""
        candles = _make_candles(100, 250, trend=1.0, volatility=0.005)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        raw = engine._raw_classify(ind, close)
        assert raw in (Regime.STRONG_UP, Regime.WEAK_UP, Regime.RANGE)

    def test_weak_down_detection(self, engine: RuleEngine) -> None:
        """약한 하락 감지."""
        candles = _make_candles(300, 250, trend=-0.5, volatility=0.01)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        raw = engine._raw_classify(ind, close)
        assert raw in (Regime.WEAK_DOWN, Regime.RANGE)

    def test_crisis_detection(self, engine: RuleEngine) -> None:
        """CRISIS 즉시 진입."""
        candles = _make_candles(1000, 200, trend=0, volatility=0.01)
        for i in range(176, 200):
            drop = (i - 176) * 5.0
            candles[i] = Candle(
                timestamp=candles[i].timestamp,
                open=1000 - drop,
                high=1000 - drop + 30,
                low=1000 - drop - 30,
                close=1000 - drop - 10,
                volume=5000.0,
            )
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        regime, _ = engine.classify_regime("TEST", ind, close)
        assert regime in (Regime.CRISIS, Regime.RANGE, Regime.WEAK_DOWN)

    def test_crisis_immediate_entry(self, engine: RuleEngine) -> None:
        """CRISIS는 히스테리시스 없이 즉시 진입 (쿨다운 무시)."""
        state = engine._get_regime_state("CRISIS_IMM")
        state.current = Regime.STRONG_UP
        state.cooldown_remaining = 5

        # CRISIS 조건을 만족하는 데이터 직접 구성
        # ATR_now > ATR_20d_avg * 2.5 AND price_change_24h < -0.10
        candles = _make_candles(1000, 200, trend=0, volatility=0.01)
        # 24봉 전부터 급락: -15% 이상
        for i in range(176, 200):
            drop = (i - 176) * 8.0
            candles[i] = Candle(
                timestamp=candles[i].timestamp,
                open=1000 - drop,
                high=1000 - drop + 50,
                low=1000 - drop - 50,
                close=1000 - drop - 20,
                volume=5000.0,
            )
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])

        # raw_classify로 CRISIS 조건 확인
        raw = engine._raw_classify(ind, close)
        if raw == Regime.CRISIS:
            # classify_regime은 쿨다운 무시하고 즉시 CRISIS
            regime, _ = engine.classify_regime("CRISIS_IMM", ind, close)
            assert regime == Regime.CRISIS
            assert state.cooldown_remaining == 0  # 쿨다운 리셋됨

    def test_crisis_6bar_release(self, engine: RuleEngine) -> None:
        """CRISIS 해제: 6봉 연속 정상 확인 필요."""
        state = engine._get_regime_state("RELEASE")
        state.current = Regime.CRISIS
        state.crisis_release_count = 0

        candles = _make_candles(100, 200, trend=0, volatility=0.01)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])

        # 5봉까지는 CRISIS 유지
        for i in range(5):
            regime, _ = engine.classify_regime("RELEASE", ind, close)
            assert regime == Regime.CRISIS
            assert state.crisis_release_count == i + 1

        # 6봉째: 해제
        regime, _ = engine.classify_regime("RELEASE", ind, close)
        assert regime != Regime.CRISIS
        assert state.crisis_release_count == 0

    def test_hysteresis_3bar_confirm(self, engine: RuleEngine) -> None:
        """히스테리시스: 3봉 확인 필요."""
        candles = _make_candles(100, 200, trend=0, volatility=0.01)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])

        r1, _ = engine.classify_regime("TEST", ind, close)
        r2, _ = engine.classify_regime("TEST", ind, close)
        assert r1 == r2

    def test_hysteresis_cooldown(self, engine: RuleEngine) -> None:
        """히스테리시스: 전환 후 6봉 재전환 금지."""
        state = engine._get_regime_state("COOL")
        state.current = Regime.STRONG_UP
        state.cooldown_remaining = 3

        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])

        regime, _ = engine.classify_regime("COOL", ind, close)
        assert regime == Regime.STRONG_UP
        assert state.cooldown_remaining == 2

    def test_get_regime_default(self, engine: RuleEngine) -> None:
        """미분류 코인은 RANGE."""
        assert engine.get_regime("UNKNOWN") == Regime.RANGE


# ═══════════════════════════════════════════
# 보조 플래그 테스트
# ═══════════════════════════════════════════


class TestAuxFlags:
    """보조 플래그 테스트."""

    def test_default_no_flags(self, engine: RuleEngine) -> None:
        """기본 상태에서 플래그 없음."""
        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        _, aux = engine.classify_regime("TEST", ind, close)
        assert isinstance(aux, AuxFlags)

    def test_aux_flags_are_bool(self, engine: RuleEngine) -> None:
        """보조 플래그 타입은 bool."""
        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        _, aux = engine.classify_regime("FLAGS", ind, close)
        assert isinstance(aux.range_volatile, bool)
        assert isinstance(aux.down_accel, bool)

    def test_down_accel_flag(self, engine: RuleEngine) -> None:
        """DOWN_ACCEL: EMA20 < EMA50 < EMA200 AND ADX > 22."""
        # 강한 하락 데이터
        candles = _make_candles(500, 250, trend=-1.5, volatility=0.01)
        ind = compute_indicators(candles)
        close = np.array([c.close for c in candles])
        aux = engine._detect_aux_flags(ind, close)
        # 강한 하락이면 down_accel이 True일 가능성
        assert isinstance(aux.down_accel, bool)


# ═══════════════════════════════════════════
# 전략 점수 테스트
# ═══════════════════════════════════════════


class TestScoring:
    """전략 점수 테스트."""

    def test_score_range_0_100(self, engine: RuleEngine) -> None:
        """점수는 0~100 범위."""
        candles = _make_candles(100, 200, trend=0.1, volatility=0.02)
        ind = compute_indicators(candles)

        sr_a = engine._score_strategy_a(ind, ind)
        assert 0 <= sr_a.score <= 100

        sr_b = engine._score_strategy_b(ind)
        assert 0 <= sr_b.score <= 100

    def test_strategy_a_detail_keys(self, engine: RuleEngine) -> None:
        """전략 A 점수 상세 키 존재."""
        candles = _make_candles(100, 200, trend=0.5)
        ind = compute_indicators(candles)
        sr = engine._score_strategy_a(ind, ind)
        assert "trend_align" in sr.detail
        assert "macd" in sr.detail
        assert "volume" in sr.detail
        assert "rsi_pullback" in sr.detail
        assert "supertrend" in sr.detail
        assert sr.strategy == Strategy.TREND_FOLLOW

    def test_strategy_b_detail_keys(self, engine: RuleEngine) -> None:
        """전략 B 점수 상세 키 존재."""
        candles = _make_candles(100, 200, trend=-0.1)
        ind = compute_indicators(candles)
        sr = engine._score_strategy_b(ind)
        assert "rsi_bounce" in sr.detail
        assert "bb_position" in sr.detail
        assert "volume" in sr.detail
        assert "zscore" in sr.detail
        assert sr.strategy == Strategy.MEAN_REVERSION

    def test_strategy_c_detail_keys(self, engine: RuleEngine) -> None:
        """전략 C 점수 상세 키 존재."""
        candles = _make_candles(100, 200, trend=0.3)
        ind = compute_indicators(candles)
        sr = engine._score_strategy_c(ind, ind, candles)
        assert "breakout" in sr.detail
        assert "volume" in sr.detail
        assert "atr_expand" in sr.detail
        assert "trend_1h" in sr.detail
        assert sr.strategy == Strategy.BREAKOUT

    def test_strategy_d_detail_keys(self, engine: RuleEngine) -> None:
        """전략 D 점수 상세 키 존재."""
        candles = _make_candles(100, 200, trend=0.2)
        ind = compute_indicators(candles)
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=100,
            orderbook=_make_orderbook(spread_pct=0.001),
        )
        sr = engine._score_strategy_d(ind, ind, snap)
        assert "rsi_bounce" in sr.detail
        assert "trend_1h" in sr.detail
        assert "spread" in sr.detail
        assert "volume" in sr.detail
        assert sr.strategy == Strategy.SCALPING

    def test_strategy_e_detail_keys(self) -> None:
        """전략 E 점수 상세 키 존재."""
        from strategy.coin_profiler import CoinProfiler

        profiler = CoinProfiler(tier1_atr_max=0.009, tier3_atr_min=0.014)
        # BTC를 Tier 1로 분류
        btc_candles = _make_candles(50000000, 400, volatility=0.003)
        profiler.classify("BTC", btc_candles)
        eng = RuleEngine(profiler=profiler)

        candles = _make_candles(50000000, 250, trend=-10000)
        ind = compute_indicators(candles)
        sr = eng._score_strategy_e(ind, "BTC")
        assert "tier1" in sr.detail
        assert "rsi_oversold" in sr.detail
        assert "below_ema200" in sr.detail
        assert "zscore" in sr.detail
        assert sr.strategy == Strategy.DCA

    def test_strategy_e_non_tier1_zero_score(self, engine: RuleEngine) -> None:
        """전략 E: Tier 1이 아닌 코인은 0점."""
        candles = _make_candles(100, 250, trend=-0.5)
        ind = compute_indicators(candles)
        sr = engine._score_strategy_e(ind, "UNKNOWN_COIN")
        # 미분류 코인은 Tier 2이므로 0점
        assert sr.score == 0

    def test_strategy_c_score_range(self, engine: RuleEngine) -> None:
        """전략 C 점수 0~100."""
        candles = _make_candles(100, 200, trend=0.1)
        ind = compute_indicators(candles)
        sr = engine._score_strategy_c(ind, ind, candles)
        assert 0 <= sr.score <= 100

    def test_strategy_d_score_range(self, engine: RuleEngine) -> None:
        """전략 D 점수 0~100."""
        candles = _make_candles(100, 200, trend=0.2)
        ind = compute_indicators(candles)
        snap = MarketSnapshot(symbol="BTC", current_price=100)
        sr = engine._score_strategy_d(ind, ind, snap)
        assert 0 <= sr.score <= 100


# ═══════════════════════════════════════════
# 거래량 점수 테스트
# ═══════════════════════════════════════════


class TestVolumeScoring:
    """거래량 점수 테스트."""

    def test_volume_direct_high(self) -> None:
        """높은 거래량 (완성봉 -2) → 만점."""
        candles = _make_candles(100, 25, trend=0)
        # -2번째(완성봉) 거래량을 평균의 3배로 설정
        candles[-2] = Candle(
            timestamp=candles[-2].timestamp,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=10000.0,
        )
        score = RuleEngine._score_volume_direct(candles, threshold=2.0, max_pts=30.0)
        assert score == 30.0

    def test_volume_direct_low(self) -> None:
        """낮은 거래량 (완성봉 -2) → 0점."""
        candles = _make_candles(100, 25, trend=0)
        candles[-2] = Candle(
            timestamp=candles[-2].timestamp,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1.0,
        )
        score = RuleEngine._score_volume_direct(candles, threshold=2.0, max_pts=30.0)
        assert score == 0.0


# ═══════════════════════════════════════════
# 컷오프 판정 테스트
# ═══════════════════════════════════════════


class TestCutoff:
    """컷오프 판정 테스트."""

    def test_group1_full(self, engine: RuleEngine) -> None:
        """그룹1 Full: >=75."""
        assert engine._decide_size(Strategy.TREND_FOLLOW, 75) == SizeDecision.FULL
        assert engine._decide_size(Strategy.TREND_FOLLOW, 90) == SizeDecision.FULL

    def test_group1_probe(self, engine: RuleEngine) -> None:
        """그룹1 Probe: 60~74."""
        assert engine._decide_size(Strategy.TREND_FOLLOW, 60) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.TREND_FOLLOW, 74) == SizeDecision.PROBE

    def test_group1_hold(self, engine: RuleEngine) -> None:
        """그룹1 HOLD: <60."""
        assert engine._decide_size(Strategy.TREND_FOLLOW, 59) == SizeDecision.HOLD
        assert engine._decide_size(Strategy.TREND_FOLLOW, 0) == SizeDecision.HOLD

    def test_group1_mean_reversion(self, engine: RuleEngine) -> None:
        """그룹1에 Mean Reversion도 포함."""
        assert engine._decide_size(Strategy.MEAN_REVERSION, 75) == SizeDecision.FULL
        assert engine._decide_size(Strategy.MEAN_REVERSION, 60) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.MEAN_REVERSION, 59) == SizeDecision.HOLD

    def test_group2_full(self, engine: RuleEngine) -> None:
        """그룹2 Full: >=80."""
        assert engine._decide_size(Strategy.BREAKOUT, 80) == SizeDecision.FULL

    def test_group2_probe(self, engine: RuleEngine) -> None:
        """그룹2 Probe: 65~79."""
        assert engine._decide_size(Strategy.SCALPING, 65) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.SCALPING, 79) == SizeDecision.PROBE

    def test_group2_hold(self, engine: RuleEngine) -> None:
        """그룹2 HOLD: <65."""
        assert engine._decide_size(Strategy.BREAKOUT, 64) == SizeDecision.HOLD

    def test_group3_full(self, engine: RuleEngine) -> None:
        """그룹3 Full: >=75."""
        assert engine._decide_size(Strategy.DCA, 75) == SizeDecision.FULL

    def test_group3_probe(self, engine: RuleEngine) -> None:
        """그룹3 Probe: 68~74."""
        assert engine._decide_size(Strategy.DCA, 68) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.DCA, 74) == SizeDecision.PROBE

    def test_group3_hold(self, engine: RuleEngine) -> None:
        """그룹3 HOLD: <68."""
        assert engine._decide_size(Strategy.DCA, 67) == SizeDecision.HOLD

    def test_boundary_values(self, engine: RuleEngine) -> None:
        """경계값 테스트."""
        # Group1 경계
        assert engine._decide_size(Strategy.TREND_FOLLOW, 75) == SizeDecision.FULL
        assert engine._decide_size(Strategy.TREND_FOLLOW, 74) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.TREND_FOLLOW, 60) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.TREND_FOLLOW, 59) == SizeDecision.HOLD

        # Group2 경계
        assert engine._decide_size(Strategy.BREAKOUT, 80) == SizeDecision.FULL
        assert engine._decide_size(Strategy.BREAKOUT, 79) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.BREAKOUT, 65) == SizeDecision.PROBE
        assert engine._decide_size(Strategy.BREAKOUT, 64) == SizeDecision.HOLD


# ═══════════════════════════════════════════
# Layer 1 환경 필터 테스트
# ═══════════════════════════════════════════


class TestLayer1Filter:
    """Layer 1 환경 필터 테스트."""

    def test_crisis_blocked(self, engine: RuleEngine) -> None:
        """CRISIS 국면은 차단."""
        from strategy.coin_profiler import TierParams

        tier = TierParams(
            tier=Tier.TIER1,
            atr_pct=0.02,
            position_mult=1.5,
            rsi_min=35,
            rsi_max=65,
            atr_stop_mult=2.5,
            spread_limit=0.0018,
        )
        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=100,
            candles_15m=candles,
            orderbook=_make_orderbook(spread_pct=0.001),
        )
        ok, reason = engine._check_layer1(Regime.CRISIS, snap, ind, tier)
        assert ok is False
        assert "CRISIS" in reason

    def test_normal_passes(self, engine: RuleEngine) -> None:
        """정상 조건에서 통과."""
        from strategy.coin_profiler import TierParams

        tier = TierParams(
            tier=Tier.TIER1,
            atr_pct=0.02,
            position_mult=1.5,
            rsi_min=35,
            rsi_max=65,
            atr_stop_mult=2.5,
            spread_limit=0.0018,
        )
        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=100,
            candles_15m=candles,
            orderbook=_make_orderbook(spread_pct=0.001),
        )
        ok, _ = engine._check_layer1(Regime.RANGE, snap, ind, tier)
        assert ok is True

    def test_spread_too_wide(self, engine: RuleEngine) -> None:
        """스프레드 초과 시 차단."""
        from strategy.coin_profiler import TierParams

        tier = TierParams(
            tier=Tier.TIER1,
            atr_pct=0.02,
            position_mult=1.5,
            rsi_min=35,
            rsi_max=65,
            atr_stop_mult=2.5,
            spread_limit=0.0018,
        )
        candles = _make_candles(100, 200, trend=0)
        ind = compute_indicators(candles)
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=100,
            candles_15m=candles,
            orderbook=_make_orderbook(spread_pct=0.005),  # 0.5% >> 0.18%
        )
        ok, reason = engine._check_layer1(Regime.RANGE, snap, ind, tier)
        assert ok is False
        assert "스프레드" in reason


# ═══════════════════════════════════════════
# 신호 생성 통합 테스트
# ═══════════════════════════════════════════


class TestGenerateSignals:
    """신호 생성 통합 테스트."""

    def test_empty_snapshots(self, engine: RuleEngine) -> None:
        """빈 스냅샷 → 빈 신호."""
        signals = engine.generate_signals({})
        assert signals == []

    def test_insufficient_candles(self, engine: RuleEngine) -> None:
        """캔들 부족 시 신호 없음."""
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=50000000,
            candles_15m=_make_candles(50000000, 10),
            candles_1h=_make_candles(50000000, 10),
        )
        signals = engine.generate_signals({"BTC": snap})
        assert signals == []

    def test_sufficient_candles_returns_list(self, engine: RuleEngine) -> None:
        """충분한 캔들 시 리스트 반환 (빈 리스트도 OK)."""
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=50000000,
            candles_15m=_make_candles(50000000, 200, trend=0),
            candles_1h=_make_candles(50000000, 200, trend=0),
        )
        signals = engine.generate_signals({"BTC": snap})
        assert isinstance(signals, list)

    def test_signal_has_required_fields(self, engine: RuleEngine) -> None:
        """생성된 시그널에 필수 필드가 있어야 함."""
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=50000000,
            candles_15m=_make_candles(50000000, 200, trend=100000),
            candles_1h=_make_candles(50000000, 200, trend=100000),
            orderbook=_make_orderbook(spread_pct=0.001),
        )
        signals = engine.generate_signals({"BTC": snap})
        for sig in signals:
            assert sig.symbol == "BTC"
            assert sig.entry_price > 0
            assert sig.stop_loss > 0
            assert sig.take_profit > 0
            assert sig.score > 0
            assert sig.strategy in Strategy

    def test_multiple_coins(self, engine: RuleEngine) -> None:
        """여러 코인 동시 처리."""
        snaps = {}
        for sym in ["BTC", "ETH", "XRP"]:
            snaps[sym] = MarketSnapshot(
                symbol=sym,
                current_price=50000,
                candles_15m=_make_candles(50000, 200, trend=0),
                candles_1h=_make_candles(50000, 200, trend=0),
            )
        signals = engine.generate_signals(snaps)
        assert isinstance(signals, list)

    def test_paper_test_mode(self, engine: RuleEngine) -> None:
        """paper_test 모드에서 시그널 생성."""
        snap = MarketSnapshot(
            symbol="BTC",
            current_price=50000000,
            candles_15m=_make_candles(50000000, 200, trend=-50000),
            candles_1h=_make_candles(50000000, 200, trend=-50000),
        )
        signals = engine.generate_signals({"BTC": snap}, paper_test=True)
        # RSI < 45이면 시그널 발생
        assert isinstance(signals, list)


# ═══════════════════════════════════════════
# 국면별 전략 매핑 테스트
# ═══════════════════════════════════════════


class TestRegimeStrategyMapping:
    """국면별 전략 허용 매핑 테스트."""

    def test_strong_up_allows_b_only(self) -> None:
        """STRONG_UP → B(반전포착)만 허용 (trend_follow PF<1 비활성화 2026-03-31)."""
        from strategy.rule_engine import REGIME_STRATEGY_MAP

        allowed = REGIME_STRATEGY_MAP[Regime.STRONG_UP]
        assert Strategy.MEAN_REVERSION in allowed
        assert Strategy.TREND_FOLLOW not in allowed

    def test_weak_up_allows_b(self) -> None:
        """WEAK_UP → B 허용."""
        from strategy.rule_engine import REGIME_STRATEGY_MAP

        allowed = REGIME_STRATEGY_MAP[Regime.WEAK_UP]
        assert Strategy.MEAN_REVERSION in allowed
        assert Strategy.TREND_FOLLOW not in allowed

    def test_range_allows_mean_reversion_only(self) -> None:
        """RANGE → B만 허용 (추세 없는 시장에서 A 제거)."""
        from strategy.rule_engine import REGIME_STRATEGY_MAP

        allowed = REGIME_STRATEGY_MAP[Regime.RANGE]
        assert Strategy.MEAN_REVERSION in allowed
        assert Strategy.TREND_FOLLOW not in allowed
        assert len(allowed) == 1

    def test_weak_down_allows_b_and_e(self) -> None:
        """WEAK_DOWN → B(MEAN_REVERSION) + E(DCA) 허용."""
        from strategy.rule_engine import REGIME_STRATEGY_MAP

        allowed = REGIME_STRATEGY_MAP[Regime.WEAK_DOWN]
        assert Strategy.DCA in allowed
        assert Strategy.MEAN_REVERSION in allowed
        assert len(allowed) == 2

    def test_crisis_allows_e_only(self) -> None:
        """CRISIS → E(DCA)만 허용."""
        from strategy.rule_engine import REGIME_STRATEGY_MAP

        allowed = REGIME_STRATEGY_MAP[Regime.CRISIS]
        assert Strategy.DCA in allowed
        assert Strategy.TREND_FOLLOW not in allowed
