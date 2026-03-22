"""전략 파라미터 최적화 실행.

사용법:
  python scripts/optimize.py              # 전체 최적화 (4개 전략)
  python scripts/optimize.py --strategy trend_follow  # 특정 전략만
  python scripts/optimize.py --apply      # 최적 파라미터 config.yaml에 적용
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_config
from app.notify import DiscordNotifier
from backtesting.optimizer import ParameterOptimizer
from backtesting.param_grid import build_grids
from market.bithumb_api import BithumbClient
from market.market_store import MarketStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def ensure_data(
    client: BithumbClient,
    store: MarketStore,
    coins: list[str],
) -> None:
    """데이터가 없으면 다운로드한다.

    Args:
        client: 빗썸 API 클라이언트.
        store: 시장 데이터 저장소.
        coins: 대상 코인 목록.
    """
    from app.data_types import parse_raw_candles

    for coin in coins:
        existing = store.get_candles(coin, "15m", limit=1)
        if existing:
            continue
        logger.info("데이터 다운로드: %s", coin)
        for interval in ["15m", "1h"]:
            try:
                raw = await client.get_candlestick(coin, interval)
                candles = parse_raw_candles(raw)
                store.store_candles(coin, interval, candles)
            except Exception:
                logger.exception("%s %s 다운로드 실패", coin, interval)
            await asyncio.sleep(0.15)


def format_report(
    results: dict[str, list],
    baseline: dict[str, dict],
) -> str:
    """최적화 결과 리포트를 생성한다.

    Args:
        results: 전략별 OOS 결과 리스트.
        baseline: 전략별 현재 파라미터 성과.

    Returns:
        HTML 포맷 리포트 문자열.
    """
    strat_names = {
        "trend_follow": "A 추세추종",
        "mean_reversion": "B 반전포착",
        "breakout": "C 브레이크아웃",
        "scalping": "D 스캘핑",
    }

    lines = ["<b>[Optimize] 전략 최적화 결과</b>", ""]

    for key in ["trend_follow", "mean_reversion", "breakout", "scalping"]:
        name = strat_names.get(key, key)
        oos_list = results.get(key, [])
        base = baseline.get(key, {})

        if not oos_list:
            lines.append(f"<b>{name}</b>: 결과 없음")
            continue

        # Best OOS result by PF
        best = max(oos_list, key=lambda r: r.profit_factor)
        base_pf = base.get("pf", 0)
        base_wr = base.get("wr", 0)

        lines.append(f"<b>{name}</b>")
        lines.append(f"  Baseline: PF={base_pf:.2f} WR={base_wr:.0%}")
        lines.append(
            f"  Best OOS: PF={best.profit_factor:.2f}"
            f" WR={best.win_rate:.0%}"
            f" Exp={best.expectancy:.4f}"
            f" ({best.trades}건)"
        )

        # Params
        p = best.params
        param_str = " ".join(f"{k}={v}" for k, v in p.items())
        lines.append(f"  Params: {param_str}")

        # Verdict
        if best.trades < 10:
            lines.append("  판정: 거래 부족 (판단 보류)")
        elif best.profit_factor >= 1.0:
            lines.append("  판정: 적용 가능")
        elif best.profit_factor >= 0.5:
            lines.append("  판정: 개선됨 (추가 관찰)")
        else:
            lines.append("  판정: 비활성화 권장")
        lines.append("")

    return "\n".join(lines)


def apply_to_config(results: dict[str, list], config_path: Path) -> None:
    """최적 파라미터를 config.yaml에 적용한다.

    Args:
        results: 전략별 OOS 결과 리스트.
        config_path: config.yaml 파일 경로.
    """
    import yaml

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    sp = raw.get("strategy_params", {})

    for strategy, oos_list in results.items():
        if not oos_list:
            continue
        best = max(oos_list, key=lambda r: r.profit_factor)
        if best.trades < 10 or best.profit_factor < 0.5:
            continue
        # Apply params
        if strategy not in sp:
            sp[strategy] = {}
        for k, v in best.params.items():
            if k == "cutoff_full":
                continue  # cutoff는 별도 섹션
            sp[strategy][k] = round(v, 4)

    raw["strategy_params"] = sp

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            raw,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    logger.info("config.yaml 업데이트 완료")


async def main() -> None:
    """메인 실행."""
    parser = argparse.ArgumentParser(description="전략 파라미터 최적화")
    parser.add_argument("--strategy", type=str, help="특정 전략만 최적화")
    parser.add_argument("--apply", action="store_true", help="최적 파라미터 적용")
    args = parser.parse_args()

    config = load_config()
    coins = config.coins
    store = MarketStore(db_path="data/market_data.db")
    client = BithumbClient(
        api_key=config.secrets.bithumb_api_key,
        api_secret=config.secrets.bithumb_api_secret,
        base_url=config.secrets.bithumb_api_url or config.bithumb.base_url,
        proxy=config.proxy,
        verify_ssl=not bool(config.proxy),
        public_rate_limit=config.bithumb.public_rate_limit,
        private_rate_limit=config.bithumb.private_rate_limit,
    )
    notifier = DiscordNotifier(
        webhooks=config.secrets.discord_webhooks,
        proxy=config.proxy,
        timeout_sec=config.discord.timeout_sec,
    )

    try:
        # 1. 데이터 확인
        await ensure_data(client, store, coins)

        # 2. 데이터 로딩
        candles_15m: dict[str, list] = {}
        candles_1h: dict[str, list] = {}
        for coin in coins:
            candles_15m[coin] = store.get_candles(coin, "15m", limit=5000)
            candles_1h[coin] = store.get_candles(coin, "1h", limit=5000)

        # 3. Baseline (현재 파라미터)
        logger.info("Baseline 계산 중...")
        # rule_engine DEBUG 로그 끄기
        logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)

        optimizer = ParameterOptimizer(coins, config)
        baseline: dict[str, dict] = {}
        for strategy in ["trend_follow", "mean_reversion", "breakout", "scalping"]:
            current = config.strategy_params.get(strategy, {})
            r = optimizer.run_single(strategy, current, candles_15m, candles_1h)
            baseline[strategy] = {
                "pf": r.profit_factor,
                "wr": r.win_rate,
                "exp": r.expectancy,
                "trades": r.trades,
            }
            logger.info(
                "Baseline %s: %d건 PF=%.2f WR=%.0f%%",
                strategy,
                r.trades,
                r.profit_factor,
                r.win_rate * 100,
            )

        # 4. Grid Search + WF
        grids = build_grids()
        all_results: dict[str, list] = {}
        target_strategies = [args.strategy] if args.strategy else list(grids.keys())

        start = time.time()
        for strategy in target_strategies:
            grid = grids[strategy]
            combos = grid.combinations()
            oos_results = optimizer.optimize(
                strategy,
                combos,
                candles_15m,
                candles_1h,
            )
            all_results[strategy] = oos_results
        elapsed = time.time() - start
        logger.info("최적화 완료: %.0f초", elapsed)

        # 5. 리포트
        report = format_report(all_results, baseline)
        # 터미널 인코딩 문제 방지 (UTF-8 강제)
        sys.stdout.buffer.write(
            ("\n" + report.replace("<b>", "").replace("</b>", "") + "\n").encode("utf-8")
        )

        # 6. 디스코드 전송
        await notifier.send(report, channel="backtest")
        logger.info("디스코드 전송 완료")

        # 7. --apply
        if args.apply:
            config_path = ROOT / "configs" / "config.yaml"
            apply_to_config(all_results, config_path)

    finally:
        await client.close()
        await notifier.close()
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
