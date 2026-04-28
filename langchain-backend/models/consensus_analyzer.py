"""Pillar 4 — Model Consensus Analyzer (4 메트릭).

11 base 모델의 1~45 ranking 벡터를 받아 각 번호 n에 대해 다음 4 메트릭을 산출.

- mean_rank(n)       : 모델별 순위 평균 — 작을수록 추천 합의 강함
- std_rank(n)        : 모델별 순위 표준편차 — 작을수록 합의 강함 (감점 사유)
- top10_count(n)     : rank <= top_n인 모델 수 — 5+ 시 강한 추천 보너스
- bottom15_count(n)  : rank >= bottom_n인 모델 수 — 5+ 시 강한 제외 페널티

Pillar 4 점수:
    consensus_score(n) = -mean_rank(n)
                       - 0.5 * std_rank(n)
                       + 2.0 * (top10_count(n)    >= 5)
                       - 2.0 * (bottom15_count(n) >= 5)

NumberScorer 입력: shape (45, 4) 매트릭스로 변환 가능.
"""
from __future__ import annotations

import numpy as np

try:
    import config  # type: ignore
    _RANDOM_SEED = int(getattr(config, "RANDOM_SEED", 42))
except Exception:
    _RANDOM_SEED = 42


# Pillar 4 점수 공식 상수 (number-recommendation-plan)
_STD_PENALTY        = 0.5
_TOP_BONUS          = 2.0
_BOTTOM_PENALTY     = 2.0
_STRONG_AGREE_K     = 5  # top10_count / bottom15_count 임계 모델 수


class ConsensusAnalyzer:
    """Pillar 4 — 11 base 순위 통계 4 메트릭 + Consensus Score."""

    def __init__(self, top_n: int = 10, bottom_n: int = 31):
        """임계값 설정.

        Args:
            top_n   : top10_count 산정 시 rank <= top_n 인 모델 수 (default 10)
            bottom_n: bottom15_count 산정 시 rank >= bottom_n 인 모델 수 (default 31)
        """
        if not (1 <= top_n < bottom_n <= 45):
            raise ValueError(
                f"invalid threshold: top_n={top_n}, bottom_n={bottom_n} "
                "(must satisfy 1 <= top_n < bottom_n <= 45)"
            )
        self.top_n: int = int(top_n)
        self.bottom_n: int = int(bottom_n)
        self._seed: int = _RANDOM_SEED

    # ------------------------------------------------------------------
    # 1. compute_metrics
    # ------------------------------------------------------------------
    def compute_metrics(
        self,
        rankings: dict[str, list[int]],
    ) -> dict[int, dict]:
        """각 번호 n별 4 메트릭 + consensus_score 산출.

        Args:
            rankings: {model_name: [number_at_rank_1, ..., number_at_rank_45]}
                      None / 빈 list 모델은 자동 skip.

        Returns:
            {
              n: {
                "mean_rank":       float,
                "std_rank":        float,
                "top10_count":     int,
                "bottom15_count":  int,
                "consensus_score": float,
                "n_models":        int,
                "ranks":           list[int],  # 모델별 순위 (디버깅용)
              }
              for n in 1..45
            }
        """
        active = self._filter_active(rankings)
        n_models = len(active)

        if n_models == 0:
            # graceful: 모든 메트릭 0으로 반환
            return {
                n: {
                    "mean_rank": 0.0,
                    "std_rank": 0.0,
                    "top10_count": 0,
                    "bottom15_count": 0,
                    "consensus_score": 0.0,
                    "n_models": 0,
                    "ranks": [],
                }
                for n in range(1, 46)
            }

        # 모델별 number → rank 변환 (1-indexed)
        rank_table: dict[str, dict[int, int]] = {}
        for name, vec in active.items():
            rank_table[name] = {num: i + 1 for i, num in enumerate(vec)}

        metrics: dict[int, dict] = {}
        for n in range(1, 46):
            ranks = []
            for name in active:
                # 모델 ranking에 n이 없으면 최하위(46)로 처리 (방어)
                ranks.append(rank_table[name].get(n, 46))
            ranks_arr = np.asarray(ranks, dtype=np.float64)

            mean_rank = float(ranks_arr.mean())
            # ddof=0 (모표준편차) — 모델 수가 11로 적기에 해석 단순
            std_rank = float(ranks_arr.std(ddof=0))
            top_count = int((ranks_arr <= self.top_n).sum())
            bottom_count = int((ranks_arr >= self.bottom_n).sum())

            # Pillar 4 점수
            score = (
                -mean_rank
                - _STD_PENALTY * std_rank
                + _TOP_BONUS    * float(top_count    >= _STRONG_AGREE_K)
                - _BOTTOM_PENALTY * float(bottom_count >= _STRONG_AGREE_K)
            )

            metrics[n] = {
                "mean_rank":       mean_rank,
                "std_rank":        std_rank,
                "top10_count":     top_count,
                "bottom15_count":  bottom_count,
                "consensus_score": float(score),
                "n_models":        n_models,
                "ranks":           [int(r) for r in ranks],
            }
        return metrics

    # ------------------------------------------------------------------
    # 2. compute_consensus_score
    # ------------------------------------------------------------------
    def compute_consensus_score(
        self,
        metrics: dict[int, dict],
    ) -> dict[int, float]:
        """compute_metrics() 결과에서 consensus_score만 추출하는 헬퍼.

        Args:
            metrics: compute_metrics() 결과

        Returns:
            {n: consensus_score(n)}
        """
        return {n: float(m.get("consensus_score", 0.0)) for n, m in metrics.items()}

    # ------------------------------------------------------------------
    # 3. to_pillar4_features (NumberScorer 입력)
    # ------------------------------------------------------------------
    def to_pillar4_features(
        self,
        metrics: dict[int, dict],
    ) -> np.ndarray:
        """NumberScorer 입력용 (45, 4) 매트릭스 변환.

        column 순서: [mean_rank, std_rank, top10_count, bottom15_count]

        Args:
            metrics: compute_metrics() 결과

        Returns:
            np.ndarray shape (45, 4), dtype float32
        """
        arr = np.zeros((45, 4), dtype=np.float32)
        for i, n in enumerate(range(1, 46)):
            m = metrics.get(n, {})
            arr[i, 0] = float(m.get("mean_rank", 0.0))
            arr[i, 1] = float(m.get("std_rank", 0.0))
            arr[i, 2] = float(m.get("top10_count", 0))
            arr[i, 3] = float(m.get("bottom15_count", 0))
        return arr

    # ------------------------------------------------------------------
    # 4. summary
    # ------------------------------------------------------------------
    def summarize(
        self,
        metrics: dict[int, dict],
        n_top: int = 5,
        n_bottom: int = 5,
    ) -> dict:
        """Pillar 4 점수 상위/하위 요약 — XAI 페이로드용.

        Args:
            metrics : compute_metrics() 결과
            n_top   : 점수 상위 N
            n_bottom: 점수 하위 N

        Returns:
            {
              "top": [(n, score, mean_rank, top10_count), ...],
              "bottom": [(n, score, mean_rank, bottom15_count), ...],
              "n_models": int,
              "score_range": (min, max),
            }
        """
        if not metrics:
            return {"top": [], "bottom": [], "n_models": 0, "score_range": (0.0, 0.0)}

        n_models = next(iter(metrics.values())).get("n_models", 0)

        scored = [
            (n, m["consensus_score"], m["mean_rank"], m["top10_count"], m["bottom15_count"])
            for n, m in metrics.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        top = [
            {"number": n, "score": round(s, 4), "mean_rank": round(mr, 2),
             "top10_count": tc}
            for n, s, mr, tc, _ in scored[:n_top]
        ]
        bottom = [
            {"number": n, "score": round(s, 4), "mean_rank": round(mr, 2),
             "bottom15_count": bc}
            for n, s, mr, _, bc in scored[-n_bottom:][::-1]
        ]
        score_range = (round(scored[-1][1], 4), round(scored[0][1], 4))

        return {
            "top": top,
            "bottom": bottom,
            "n_models": n_models,
            "score_range": score_range,
        }

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------
    @staticmethod
    def _filter_active(
        rankings: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        """None/빈 list/잘못된 길이 모델 자동 skip."""
        active: dict[str, list[int]] = {}
        for name, vec in rankings.items():
            if vec is None:
                continue
            if not isinstance(vec, list) or len(vec) < 45:
                continue
            active[name] = vec
        return active


# ──────────────────────────────────────────────────────────────────────
# Smoke main
# ──────────────────────────────────────────────────────────────────────
def main() -> None:
    """smoke: ModelRankExtractor 가짜 ranking → 4 메트릭 + Pillar 4 점수 검증."""
    # 동일 시드로 재현되는 ranking 생성
    from models.model_rank_extractor import ModelRankExtractor  # noqa: WPS433

    rng = np.random.default_rng(_RANDOM_SEED)

    base_models = [
        "xgboost", "catboost", "tabnet",
        "cnn", "gnn", "markov",
        "autoencoder", "tft", "nbeats",
        "mhn", "bayesian_nn",
    ]
    fake_outputs: dict[str, dict[int, float] | None] = {}
    boost_targets = [3, 17, 23, 38]    # 모든 모델이 상위에 두도록 boost
    sink_targets = [1, 9, 44, 45]      # 모든 모델이 하위에 두도록 sink

    for name in base_models:
        if name in {"tabnet", "mhn"}:  # 2개 미설치 가정
            fake_outputs[name] = None
            continue
        probs = rng.dirichlet(np.ones(45) * 0.6)
        for t in boost_targets:
            probs[t - 1] += 0.08
        for t in sink_targets:
            probs[t - 1] *= 0.05
        probs = probs / probs.sum()
        fake_outputs[name] = {n: float(probs[n - 1]) for n in range(1, 46)}

    extractor = ModelRankExtractor()
    rankings = extractor.extract_rankings(fake_outputs)

    analyzer = ConsensusAnalyzer(top_n=10, bottom_n=31)

    print("[ConsensusAnalyzer] smoke start")
    print(f"  active models: {len(rankings)}/{len(base_models)}")
    print(f"  thresholds   : top_n={analyzer.top_n}, bottom_n={analyzer.bottom_n}")

    # 1. compute_metrics
    metrics = analyzer.compute_metrics(rankings)
    print(f"\n  [1] compute_metrics: {len(metrics)} numbers")
    # boost_targets 체크: top10_count 가 높아야 함
    for t in boost_targets:
        m = metrics[t]
        print(
            f"      boost  n={t:2d}: mean={m['mean_rank']:5.2f} "
            f"std={m['std_rank']:5.2f} top10={m['top10_count']} "
            f"bot15={m['bottom15_count']} score={m['consensus_score']:7.3f}"
        )
    for t in sink_targets:
        m = metrics[t]
        print(
            f"      sink   n={t:2d}: mean={m['mean_rank']:5.2f} "
            f"std={m['std_rank']:5.2f} top10={m['top10_count']} "
            f"bot15={m['bottom15_count']} score={m['consensus_score']:7.3f}"
        )

    # 2. compute_consensus_score
    scores = analyzer.compute_consensus_score(metrics)
    assert len(scores) == 45
    top5 = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
    bot5 = sorted(scores.items(), key=lambda kv: kv[1])[:5]
    print(f"\n  [2] consensus_score top5 : {[(n, round(s,2)) for n,s in top5]}")
    print(f"      consensus_score bot5 : {[(n, round(s,2)) for n,s in bot5]}")

    # 3. to_pillar4_features
    feats = analyzer.to_pillar4_features(metrics)
    print(f"\n  [3] to_pillar4_features shape={feats.shape} dtype={feats.dtype}")
    print(f"      col mean_rank      avg = {feats[:,0].mean():.2f}")
    print(f"      col std_rank       avg = {feats[:,1].mean():.2f}")
    print(f"      col top10_count    avg = {feats[:,2].mean():.2f}")
    print(f"      col bottom15_count avg = {feats[:,3].mean():.2f}")
    assert feats.shape == (45, 4)
    assert feats.dtype == np.float32

    # 4. summarize
    summary = analyzer.summarize(metrics)
    print(f"\n  [4] summarize:")
    print(f"      n_models      : {summary['n_models']}")
    print(f"      score_range   : {summary['score_range']}")
    print(f"      top score    : {summary['top']}")
    print(f"      bottom score : {summary['bottom']}")

    # 정합성 검증
    boost_in_top = {item["number"] for item in summary["top"]}
    sink_in_bottom = {item["number"] for item in summary["bottom"]}
    overlap_top = boost_in_top & set(boost_targets)
    overlap_bot = sink_in_bottom & set(sink_targets)
    print(
        f"\n  consensus check: boost_targets & top5 = {sorted(overlap_top)}, "
        f"sink_targets & bottom5 = {sorted(overlap_bot)}"
    )
    assert len(overlap_top) >= 1, "boost target must appear in top5 at least once"
    assert len(overlap_bot) >= 1, "sink target must appear in bottom5 at least once"

    # graceful: 모든 모델 None 시
    metrics_empty = analyzer.compute_metrics({m: None for m in base_models})
    assert all(v["n_models"] == 0 for v in metrics_empty.values())
    print("\n  graceful empty: n_models all 0 OK")

    print("\n[ConsensusAnalyzer] smoke OK")


if __name__ == "__main__":
    main()
