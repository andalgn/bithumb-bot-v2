"""AutoResearcher — 자율 전략 실험 엔진.

DeepSeek LLM을 활용하여 파라미터 변경을 제안받고,
백테스트로 검증한 뒤 개선된 결과만 유지한다.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from backtesting.optimizer import OptResult, ParameterOptimizer
from market.market_store import MarketStore
from strategy.experiment_store import ExperimentStore

logger = logging.getLogger(__name__)

PARAM_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "trend_follow": {
        "sl_mult": (1.0, 5.0),
        "tp_rr": (1.0, 5.0),
        "cutoff_full": (55, 90),
        "w_trend_align": (0, 45),
        "w_macd": (0, 40),
        "w_volume": (0, 35),
        "w_rsi_pullback": (0, 30),
        "w_supertrend": (0, 25),
    },
    "mean_reversion": {
        "sl_mult": (2.0, 10.0),
        "tp_rr": (1.0, 4.0),
    },
    "dca": {
        "sl_pct": (0.02, 0.08),
        "tp_pct": (0.01, 0.05),
    },
}


@dataclass
class ExperimentResult:
    """단일 실험 결과."""

    experiment_id: str = ""
    strategy: str = ""
    params_changed: dict = field(default_factory=dict)
    baseline_pf: float = 0.0
    result_pf: float = 0.0
    baseline_sharpe: float = 0.0
    result_sharpe: float = 0.0
    trades: int = 0
    mdd: float = 0.0
    verdict: str = ""  # KEEP / REVERT
    description: str = ""


class AutoResearcher:
    """DeepSeek 기반 자율 전략 실험 엔진."""

    def __init__(
        self,
        store: object,
        coins: list[str],
        deepseek_api_key: str,
        deepseek_base_url: str = "https://api.deepseek.com/v1",
        max_experiments: int = 10,
        max_consecutive_failures: int = 5,
        log_path: Path | None = None,
        experiment_store: ExperimentStore | None = None,
    ) -> None:
        """초기화.

        Args:
            store: MarketStore 인스턴스.
            coins: 대상 코인 목록.
            deepseek_api_key: DeepSeek API 키.
            deepseek_base_url: DeepSeek API URL.
            max_experiments: 세션당 최대 실험 횟수.
            max_consecutive_failures: 연속 REVERT 최대 횟수 (초과 시 중단).
            log_path: TSV 로그 파일 경로.
            experiment_store: ExperimentStore 인스턴스 (실패 이력 조회/기록용).
        """
        self._store: MarketStore = store  # type: ignore[assignment]
        self._coins = coins
        self._deepseek_key = deepseek_api_key
        self._deepseek_url = deepseek_base_url
        self._max_experiments = max_experiments
        self._max_consecutive_failures = max_consecutive_failures
        self._log_path = log_path or Path("data/research_log.tsv")
        self._experiment_store = experiment_store
        self._min_pf = 1.0
        self._min_trades = 20
        self._max_mdd = 0.15

    # ═══════════════════════════════════════════
    # 메인 세션
    # ═══════════════════════════════════════════

    async def run_session(self) -> list[ExperimentResult]:
        """자율 실험 세션을 실행한다.

        설정 로딩 → 캔들 로딩 → 전략별 베이스라인 계산 → 실험 루프.
        PARAM_BOUNDS에 정의된 모든 전략에 대해 실험을 수행한다.

        Returns:
            실험 결과 리스트.
        """
        from app.config import load_config

        # 전략/백테스트 로거 억제
        logging.getLogger("strategy.rule_engine").setLevel(logging.WARNING)
        logging.getLogger("backtesting.optimizer").setLevel(logging.WARNING)

        config = load_config()

        candles_15m, candles_1h = self._load_candles()
        if not candles_15m:
            logger.warning("캔들 데이터 없음, 세션 종료")
            return []

        optimizer = ParameterOptimizer(self._coins, config)

        # 활성 전략 결정: config에 파라미터가 있는 전략 우선
        strategies = list(PARAM_BOUNDS.keys())
        active_strategies = [s for s in strategies if config.strategy_params.get(s)]
        inactive_strategies = [s for s in strategies if s not in active_strategies]
        ordered_strategies = active_strategies + inactive_strategies

        all_results: list[ExperimentResult] = []
        history = self._load_history()

        for strategy in ordered_strategies:
            current_params = dict(config.strategy_params.get(strategy, {}))
            if not current_params:
                logger.info("전략 '%s': config에 파라미터 없음, 건너뜀", strategy)
                continue

            # 베이스라인 계산
            baseline = optimizer.run_single(strategy, current_params, candles_15m, candles_1h)
            logger.info(
                "[%s] 베이스라인: PF=%.2f, Sharpe=%.2f, trades=%d, MDD=%.2f%%",
                strategy,
                baseline.profit_factor,
                baseline.sharpe,
                baseline.trades,
                baseline.max_drawdown * 100,
            )

            consecutive_failures = 0
            experiments_per_strategy = max(self._max_experiments // len(ordered_strategies), 3)

            for i in range(experiments_per_strategy):
                if consecutive_failures >= self._max_consecutive_failures:
                    logger.info(
                        "[%s] 연속 %d회 REVERT, 전략 실험 중단",
                        strategy,
                        consecutive_failures,
                    )
                    break

                logger.info(
                    "[%s] 실험 %d/%d 시작",
                    strategy,
                    i + 1,
                    experiments_per_strategy,
                )

                # DeepSeek 제안
                proposal = await self._propose_experiment(
                    strategy,
                    current_params,
                    baseline,
                    history[-10:],
                )
                if proposal is None:
                    logger.warning("[%s] 제안 파싱 실패, 건너뜀", strategy)
                    consecutive_failures += 1
                    continue

                new_params = {**current_params, **proposal["params"]}

                # 범위 검증
                if not self._validate_bounds(strategy, new_params):
                    logger.warning(
                        "[%s] 파라미터 범위 초과, 건너뜀: %s",
                        strategy,
                        proposal["params"],
                    )
                    consecutive_failures += 1
                    continue

                # 백테스트 (캐시 리셋으로 가중치 변경 반영)
                optimizer._entry_cache = {}
                result = optimizer.run_single(strategy, new_params, candles_15m, candles_1h)

                # 평가
                is_better = self._evaluate(result, baseline)
                exp_id = uuid.uuid4().hex[:8]
                verdict = "KEEP" if is_better else "REVERT"

                exp = ExperimentResult(
                    experiment_id=exp_id,
                    strategy=strategy,
                    params_changed=proposal["params"],
                    baseline_pf=baseline.profit_factor,
                    result_pf=result.profit_factor,
                    baseline_sharpe=baseline.sharpe,
                    result_sharpe=result.sharpe,
                    trades=result.trades,
                    mdd=result.max_drawdown,
                    verdict=verdict,
                    description=proposal.get("hypothesis", ""),
                )
                all_results.append(exp)
                history.append(exp)
                self._log_result(exp)

                # ExperimentStore에 기록
                if self._experiment_store:
                    self._experiment_store.record(
                        source="auto_research",
                        strategy=strategy,
                        params=proposal.get("params", {}),
                        old_params=current_params,
                        pf=result.profit_factor,
                        mdd=result.max_drawdown,
                        trades=result.trades,
                        verdict="keep" if is_better else "revert",
                    )

                if is_better:
                    logger.info(
                        "[%s] KEEP: PF %.2f→%.2f, Sharpe %.2f→%.2f",
                        strategy,
                        baseline.profit_factor,
                        result.profit_factor,
                        baseline.sharpe,
                        result.sharpe,
                    )
                    baseline = result
                    current_params = new_params
                    consecutive_failures = 0
                else:
                    logger.info(
                        "[%s] REVERT: PF %.2f→%.2f, trades=%d, MDD=%.2f%%",
                        strategy,
                        baseline.profit_factor,
                        result.profit_factor,
                        result.trades,
                        result.max_drawdown * 100,
                    )
                    consecutive_failures += 1

        kept = sum(1 for r in all_results if r.verdict == "KEEP")
        logger.info("세션 완료: %d건 실험, %d건 KEEP", len(all_results), kept)
        return all_results

    # ═══════════════════════════════════════════
    # 캔들 로딩
    # ═══════════════════════════════════════════

    def _load_candles(self) -> tuple[dict, dict]:
        """MarketStore에서 15분/1시간 캔들을 로딩한다.

        Returns:
            (candles_15m, candles_1h) 딕셔너리 튜플.
        """
        candles_15m: dict = {}
        candles_1h: dict = {}
        for coin in self._coins:
            c15 = self._store.get_candles(coin, "15m", limit=5000)
            c1h = self._store.get_candles(coin, "1h", limit=2000)
            if c15:
                candles_15m[coin] = c15
            if c1h:
                candles_1h[coin] = c1h
        logger.info(
            "캔들 로딩: 15m %d코인, 1h %d코인",
            len(candles_15m),
            len(candles_1h),
        )
        return candles_15m, candles_1h

    # ═══════════════════════════════════════════
    # DeepSeek 제안
    # ═══════════════════════════════════════════

    async def _propose_experiment(
        self,
        strategy: str,
        current_params: dict,
        baseline: OptResult,
        recent_history: list[ExperimentResult],
    ) -> dict | None:
        """DeepSeek API를 호출하여 파라미터 변경을 제안받는다.

        Args:
            strategy: 전략 이름.
            current_params: 현재 파라미터.
            baseline: 베이스라인 결과.
            recent_history: 최근 실험 이력.

        Returns:
            제안 딕셔너리 또는 None.
        """
        from app.llm_client import call_claude

        # research_program.md 내용 로딩
        program_content = ""
        program_path = Path("docs/research_program.md")
        if program_path.exists():
            program_content = program_path.read_text(encoding="utf-8")

        history_text = ""
        for h in recent_history:
            history_text += (
                f"  - {h.experiment_id}: {h.params_changed} → "
                f"PF {h.baseline_pf:.2f}→{h.result_pf:.2f}, "
                f"verdict={h.verdict}\n"
            )

        bounds_text = json.dumps(PARAM_BOUNDS.get(strategy, {}), indent=2)

        # ExperimentStore에서 실패 이력 조회
        failure_text = ""
        if self._experiment_store:
            failures = self._experiment_store.get_history(strategy, limit=10)
            failed_params = [f for f in failures if f.get("verdict") in ("revert", "rolled_back")]
            if failed_params:
                failure_text = "\n\n## 이전 실패 실험 (피해야 할 방향):\n"
                for fp in failed_params[:5]:
                    failure_text += (
                        f"  - params={fp.get('params')}, "
                        f"PF={fp.get('pf', 0):.3f}, "
                        f"verdict={fp.get('verdict')}\n"
                    )

        prompt = (
            "당신은 암호화폐 자동매매 전략 파라미터 최적화 연구원입니다.\n\n"
            f"## 연구 프로그램\n{program_content}\n\n"
            f"## 현재 전략: {strategy}\n"
            f"## 현재 파라미터:\n{json.dumps(current_params, indent=2)}\n\n"
            f"## 베이스라인 성과:\n"
            f"- Profit Factor: {baseline.profit_factor:.3f}\n"
            f"- Sharpe: {baseline.sharpe:.3f}\n"
            f"- Win Rate: {baseline.win_rate:.1%}\n"
            f"- Trades: {baseline.trades}\n"
            f"- MDD: {baseline.max_drawdown:.2%}\n\n"
            f"## 파라미터 허용 범위:\n{bounds_text}\n\n"
            f"## 최근 실험 이력:\n{history_text or '  (없음)'}\n"
            f"{failure_text}\n"
            "## 지시사항\n"
            "한 가지 파라미터 변경 실험을 JSON으로 제안하세요.\n"
            "이전 실패 실험과 동일한 방향의 변경은 피하세요.\n"
            "반드시 아래 형식만 출력하세요:\n"
            '```json\n{"params": {"파라미터명": 값}, '
            '"hypothesis": "가설", "expected_impact": "예상 효과"}\n```'
        )

        response = await call_claude(prompt, model="sonnet", timeout=60)
        if not response:
            logger.warning("Claude 실험 제안 호출 실패")
            return None

        return self._parse_proposal(response)

    def _parse_proposal(self, content: str) -> dict | None:
        """DeepSeek 응답에서 JSON 제안을 파싱한다.

        Args:
            content: LLM 응답 텍스트.

        Returns:
            파싱된 딕셔너리 또는 None.
        """
        # ```json ... ``` 블록 추출
        match = re.search(r"```json\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if "params" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # raw JSON 추출
        match = re.search(r"\{[^{}]*\"params\"[^{}]*\{[^{}]*\}[^{}]*\}", content)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if "params" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        logger.warning("JSON 파싱 실패: %s", content[:200])
        return None

    # ═══════════════════════════════════════════
    # 검증
    # ═══════════════════════════════════════════

    def _validate_bounds(self, strategy: str, params: dict) -> bool:
        """파라미터가 허용 범위 내인지 검증한다.

        Args:
            strategy: 전략 이름.
            params: 검증할 파라미터.

        Returns:
            모든 파라미터가 범위 내이면 True.
        """
        bounds = PARAM_BOUNDS.get(strategy, {})
        for key, value in params.items():
            if key not in bounds:
                continue
            lo, hi = bounds[key]
            if not (lo <= float(value) <= hi):
                logger.warning(
                    "범위 초과: %s=%s (허용: %.1f~%.1f)",
                    key,
                    value,
                    lo,
                    hi,
                )
                return False
        return True

    def _evaluate(self, result: OptResult, baseline: OptResult) -> bool:
        """실험 결과가 베이스라인 대비 개선인지 평가한다.

        Args:
            result: 실험 결과.
            baseline: 베이스라인 결과.

        Returns:
            개선이면 True.
        """
        if result.profit_factor <= baseline.profit_factor:
            return False
        if result.max_drawdown > self._max_mdd:
            return False
        if result.trades < self._min_trades:
            return False
        return True

    # ═══════════════════════════════════════════
    # TSV 로깅
    # ═══════════════════════════════════════════

    def _load_history(self) -> list[ExperimentResult]:
        """TSV 파일에서 실험 이력을 로딩한다.

        Returns:
            ExperimentResult 리스트.
        """
        if not self._log_path.exists():
            return []

        results: list[ExperimentResult] = []
        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) <= 1:
            return results

        for line in lines[1:]:  # 헤더 스킵
            parts = line.split("\t")
            if len(parts) < 11:
                continue
            try:
                results.append(
                    ExperimentResult(
                        experiment_id=parts[0],
                        strategy=parts[1],
                        params_changed=json.loads(parts[2]),
                        baseline_pf=float(parts[3]),
                        result_pf=float(parts[4]),
                        baseline_sharpe=float(parts[5]),
                        result_sharpe=float(parts[6]),
                        trades=int(parts[7]),
                        mdd=float(parts[8]),
                        verdict=parts[9],
                        description=parts[10],
                    )
                )
            except (ValueError, json.JSONDecodeError):
                continue
        return results

    def _log_result(self, exp: ExperimentResult) -> None:
        """실험 결과를 TSV 파일에 추가한다.

        Args:
            exp: 기록할 실험 결과.
        """
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self._log_path.exists()

        with open(self._log_path, "a", encoding="utf-8") as f:
            if write_header:
                f.write(
                    "experiment_id\tstrategy\tparams_changed\t"
                    "baseline_pf\tresult_pf\tbaseline_sharpe\tresult_sharpe\t"
                    "trades\tmdd\tverdict\tdescription\n"
                )
            f.write(
                f"{exp.experiment_id}\t{exp.strategy}\t"
                f"{json.dumps(exp.params_changed, ensure_ascii=False)}\t"
                f"{exp.baseline_pf:.4f}\t{exp.result_pf:.4f}\t"
                f"{exp.baseline_sharpe:.4f}\t{exp.result_sharpe:.4f}\t"
                f"{exp.trades}\t{exp.mdd:.4f}\t"
                f"{exp.verdict}\t{exp.description}\n"
            )
