"""Phase 1~4 22 predictor 통합 학습/추론/저장 파이프라인.

Master Plan Stage 1-4-B. phase1_registry + endings/ac/sum predictor를 Phase 위계 따라
일괄 학습한다. cross-feedback 입력 자동 전달.

Phase 위계:
  Phase 1 (독립, 19): phase1_registry — digit/decade/gung/multiple/categorical(6)/
                                          special(6)/missing/hotcold/lotto_paper
  Phase 2 (Phase 1): endings_predictor (끝수합 + 분포 10D)
  Phase 3 (Phase 1+2): ac_predictor (AC, Markov 11-state)
  Phase 4 (모두): sum_predictor (총합, sum 카르텟)

본 클래스는 weekly_pipeline_v2._run_analysis() 와 training_orchestrator에서 호출.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import config


class PredictorPipeline:
    """Phase 1~4 통합 파이프라인."""

    def __init__(self, feature_dim: int = 24):
        self.feature_dim = feature_dim

        # Phase 1
        from predictors.phase1_registry import Phase1Registry
        self.phase1 = Phase1Registry(feature_dim=feature_dim)
        self.phase1.register_default()

        # Phase 2/3/4 (lazy import — 학습 시점에만 인스턴스 생성)
        self.endings = None
        self.ac = None
        self.sum_pred = None  # 'sum'은 builtin이라 sum_pred로

        # Stage 2: 회귀 (4 Tier)
        self.regression = None  # DynamicIndependentCountPredictor
        self.regression_meta = None  # RegressionMetaAnalyzer

        self._train_status: dict[str, dict] = {}
        self._is_trained = False

    # ────── 학습 ──────

    def train(self, draws: list[dict], min_history: int = 50) -> dict:
        """Phase 1 -> 2 -> 3 -> 4 순차 학습. cross-feedback 입력 자동 전달."""
        results = {}
        t_start = time.time()

        # Phase 1
        try:
            p1_results = self.phase1.train_all(draws, min_history=min_history)
            results["phase1"] = {
                "status": "ok",
                "n_predictors": len(self.phase1.predictors),
                "trained": [name for name, status in self.phase1._train_status.items() if status == "trained"],
            }
            self._train_status["phase1"] = results["phase1"]
        except Exception as e:
            results["phase1"] = {"status": "fail", "error": str(e)}
            self._train_status["phase1"] = results["phase1"]

        # Phase 1 출력 (cross-feedback 입력으로 사용)
        try:
            p1_outputs = self.phase1.predict_all(draws[:min_history * 2] if len(draws) > min_history * 2 else draws)
        except Exception as e:
            print(f"  [PredictorPipeline] phase1 predict_all fail: {e}")
            p1_outputs = None

        # Phase 2
        try:
            from predictors.endings_predictor import EndingsPredictor
            self.endings = EndingsPredictor(feature_dim=self.feature_dim)
            self.endings.train(draws, phase1_outputs=p1_outputs)
            results["phase2"] = {"status": "ok", "predictor": "endings"}
        except Exception as e:
            print(f"  [PredictorPipeline] phase2 (endings) train fail: {e}")
            results["phase2"] = {"status": "fail", "error": str(e)}
        self._train_status["phase2"] = results["phase2"]

        # Phase 2 출력
        p2_outputs = None
        if self.endings is not None:
            try:
                p2_outputs = self.endings.predict(draws, phase1_outputs=p1_outputs)
            except Exception as e:
                print(f"  [PredictorPipeline] phase2 predict fail: {e}")

        # Phase 3
        try:
            from predictors.ac_predictor import ACPredictor
            self.ac = ACPredictor(feature_dim=self.feature_dim)
            self.ac.train(draws, phase1_outputs=p1_outputs, phase2_endings=p2_outputs)
            results["phase3"] = {"status": "ok", "predictor": "ac"}
        except Exception as e:
            print(f"  [PredictorPipeline] phase3 (ac) train fail: {e}")
            results["phase3"] = {"status": "fail", "error": str(e)}
        self._train_status["phase3"] = results["phase3"]

        # Phase 3 출력
        p3_outputs = None
        if self.ac is not None:
            try:
                p3_outputs = self.ac.predict(
                    draws, phase1_outputs=p1_outputs, phase2_endings=p2_outputs
                )
            except Exception as e:
                print(f"  [PredictorPipeline] phase3 predict fail: {e}")

        # Phase 4
        try:
            from predictors.sum_predictor import SumPredictor
            self.sum_pred = SumPredictor(feature_dim=self.feature_dim)
            self.sum_pred.train(
                draws,
                phase1_outputs=p1_outputs,
                phase2_endings=p2_outputs,
                phase3_ac=p3_outputs,
            )
            results["phase4"] = {"status": "ok", "predictor": "sum"}
        except Exception as e:
            print(f"  [PredictorPipeline] phase4 (sum) train fail: {e}")
            results["phase4"] = {"status": "fail", "error": str(e)}
        self._train_status["phase4"] = results["phase4"]

        # Stage 2: 회귀 (4 Tier) — Phase 4와 무관하므로 cross-feedback 입력 X
        try:
            from predictors.regression_predictor import DynamicIndependentCountPredictor
            self.regression = DynamicIndependentCountPredictor(
                feature_dim=self.feature_dim,
                sample_threshold=config.REGRESSION_SAMPLE_THRESHOLD,
            )
            self.regression.train(draws)
            results["regression_tier1"] = {"status": "ok", "predictor": "regression_dynamic_icp"}
        except Exception as e:
            print(f"  [PredictorPipeline] regression Tier 1 train fail: {e}")
            results["regression_tier1"] = {"status": "fail", "error": str(e)}
        self._train_status["regression_tier1"] = results["regression_tier1"]

        # Tier 4 (메타 분석) — 별도 분석, predictor 학습 후 패턴 빈도만
        try:
            from services.regression_meta_analyzer import RegressionMetaAnalyzer
            self.regression_meta = RegressionMetaAnalyzer(
                frequency_min=config.REGRESSION_META_FREQUENCY_MIN,
                support_min=config.REGRESSION_META_SUPPORT_MIN,
            )
            self.regression_meta.analyze_patterns(draws)
            results["regression_tier4"] = {"status": "ok", "analyzer": "regression_meta"}
        except Exception as e:
            print(f"  [PredictorPipeline] regression Tier 4 fail: {e}")
            results["regression_tier4"] = {"status": "fail", "error": str(e)}
        self._train_status["regression_tier4"] = results["regression_tier4"]

        self._is_trained = True
        results["wall_time_total"] = time.time() - t_start
        return results

    # ────── 추론 ──────

    def predict_all(self, draws_so_far: list[dict]) -> dict:
        """전체 22 predictor 추론. cross-feedback 자동 전달."""
        if not self._is_trained:
            return {"error": "not_trained"}

        out = {}

        # Phase 1
        try:
            p1_outputs = self.phase1.predict_all(draws_so_far)
            out["phase1"] = p1_outputs
        except Exception as e:
            out["phase1"] = {"error": str(e)}
            p1_outputs = None

        # Phase 2
        if self.endings is not None:
            try:
                p2 = self.endings.predict(draws_so_far, phase1_outputs=p1_outputs)
                out["phase2"] = p2
            except Exception as e:
                out["phase2"] = {"error": str(e)}
                p2 = None
        else:
            p2 = None

        # Phase 3
        if self.ac is not None:
            try:
                p3 = self.ac.predict(
                    draws_so_far, phase1_outputs=p1_outputs, phase2_endings=p2
                )
                out["phase3"] = p3
            except Exception as e:
                out["phase3"] = {"error": str(e)}
                p3 = None
        else:
            p3 = None

        # Phase 4
        if self.sum_pred is not None:
            try:
                p4 = self.sum_pred.predict(
                    draws_so_far,
                    phase1_outputs=p1_outputs,
                    phase2_endings=p2,
                    phase3_ac=p3,
                )
                out["phase4"] = p4
            except Exception as e:
                out["phase4"] = {"error": str(e)}

        # Stage 2: 회귀 (Tier 1 + Tier 3 자동 룰 + Tier 4 메타)
        if self.regression is not None:
            try:
                tier1_out = self.regression.predict(draws_so_far)
                # Tier 3 자동 룰 (회귀 features 입력)
                from features.regression_features import build_regression_features_matrix_full
                from services.regression_filter_rules import apply_all_regression_rules
                target_round = draws_so_far[0]["round"] + 1 if draws_so_far else 0
                active_n = list(tier1_out.get("active_N_set", []))
                regression_features = build_regression_features_matrix_full(draws_so_far)
                tier3_rules = apply_all_regression_rules(
                    target_round=target_round,
                    draws=draws_so_far,
                    active_n_list=active_n,
                    regression_features=regression_features,
                )
                # Tier 4 (메타 패턴 + MHN retrieve)
                tier4_meta = None
                if self.regression_meta is not None:
                    try:
                        tier4_meta = {
                            "frequent_patterns": self.regression_meta.frequent_patterns,
                            "similar_rounds": self.regression_meta.retrieve_similar_rounds(
                                draws_so_far[0] if draws_so_far else None, top_k=5
                            ) if hasattr(self.regression_meta, "retrieve_similar_rounds") else None,
                        }
                    except Exception:
                        tier4_meta = None
                out["regression"] = {
                    "tier1": tier1_out,
                    "tier3_rules": tier3_rules,
                    "tier4_meta": tier4_meta,
                }
            except Exception as e:
                out["regression"] = {"error": str(e)}

        return out

    # ────── persistence ──────

    def save_all(self, save_dir: Optional[str] = None) -> dict:
        save_dir = save_dir or os.path.join(config.MODEL_DIR, "predictor_pipeline")
        os.makedirs(save_dir, exist_ok=True)
        paths = {}

        # Phase 1
        try:
            phase1_dir = os.path.join(save_dir, "phase1")
            os.makedirs(phase1_dir, exist_ok=True)
            paths["phase1"] = self.phase1.save_all(phase1_dir)
        except Exception as e:
            paths["phase1_error"] = str(e)

        # Phase 2/3/4
        for name, predictor in (("endings", self.endings), ("ac", self.ac), ("sum", self.sum_pred)):
            if predictor is not None and hasattr(predictor, "save"):
                try:
                    p = os.path.join(save_dir, f"{name}.pkl")
                    predictor.save(p)
                    paths[name] = p
                except Exception as e:
                    paths[f"{name}_error"] = str(e)

        return paths

    def load_all(self, save_dir: Optional[str] = None) -> dict:
        save_dir = save_dir or os.path.join(config.MODEL_DIR, "predictor_pipeline")
        loaded = {}

        # Phase 1
        try:
            phase1_dir = os.path.join(save_dir, "phase1")
            loaded["phase1"] = self.phase1.load_all(phase1_dir)
        except Exception as e:
            loaded["phase1_error"] = str(e)

        # Phase 2/3/4 (lazy import + load)
        for name, factory_name in (
            ("endings", "EndingsPredictor"),
            ("ac", "ACPredictor"),
            ("sum", "SumPredictor"),
        ):
            p = os.path.join(save_dir, f"{name}.pkl")
            if os.path.exists(p):
                try:
                    if name == "endings":
                        from predictors.endings_predictor import EndingsPredictor
                        self.endings = EndingsPredictor(feature_dim=self.feature_dim)
                        self.endings.load(p)
                    elif name == "ac":
                        from predictors.ac_predictor import ACPredictor
                        self.ac = ACPredictor(feature_dim=self.feature_dim)
                        self.ac.load(p)
                    elif name == "sum":
                        from predictors.sum_predictor import SumPredictor
                        self.sum_pred = SumPredictor(feature_dim=self.feature_dim)
                        self.sum_pred.load(p)
                    loaded[name] = p
                except Exception as e:
                    loaded[f"{name}_error"] = str(e)

        self._is_trained = (
            bool(self.phase1.predictors)
            or self.endings is not None
            or self.ac is not None
            or self.sum_pred is not None
        )
        return loaded

    def status_report(self) -> dict:
        return {
            "is_trained": self._is_trained,
            "feature_dim": self.feature_dim,
            "phase1_n_predictors": len(self.phase1.predictors),
            "phase1_train_status": self.phase1._train_status,
            "phase2_endings": "trained" if self.endings is not None else "not_trained",
            "phase3_ac": "trained" if self.ac is not None else "not_trained",
            "phase4_sum": "trained" if self.sum_pred is not None else "not_trained",
            "train_status": dict(self._train_status),
        }

    # ────── orchestrator 등록 ──────

    def register_to_orchestrator(self, orch) -> None:
        """training_orchestrator.TrainingOrchestrator에 4 stage 등록.

        Stage 1: phase1_all (19 predictor 묶음)
        Stage 2: endings (depends_on phase1_all)
        Stage 3: ac (depends_on endings)
        Stage 4: sum (depends_on ac)
        """
        from pipeline.training_orchestrator import (
            PredictorEntry,
            STAGE_PHASE1, STAGE_PHASE2, STAGE_PHASE3, STAGE_PHASE4,
        )

        # Stage 1
        def _train_phase1(draws):
            return self.phase1.train_all(draws)
        orch.register(PredictorEntry(
            predictor_id="phase1_all",
            stage=STAGE_PHASE1,
            train_fn=_train_phase1,
            cache_key="phase1_all",
        ))

        # Stage 2
        def _train_endings(draws):
            from predictors.endings_predictor import EndingsPredictor
            if self.endings is None:
                self.endings = EndingsPredictor(feature_dim=self.feature_dim)
            try:
                p1_outputs = self.phase1.predict_all(draws)
            except Exception:
                p1_outputs = None
            self.endings.train(draws, phase1_outputs=p1_outputs)
            return {"success": True, "phase": 2, "predictor": "endings"}
        orch.register(PredictorEntry(
            predictor_id="endings",
            stage=STAGE_PHASE2,
            train_fn=_train_endings,
            cache_key="endings",
            depends_on=["phase1_all"],
        ))

        # Stage 3
        def _train_ac(draws):
            from predictors.ac_predictor import ACPredictor
            if self.ac is None:
                self.ac = ACPredictor(feature_dim=self.feature_dim)
            try:
                p1_outputs = self.phase1.predict_all(draws)
                p2_outputs = self.endings.predict(draws, phase1_outputs=p1_outputs) if self.endings else None
            except Exception:
                p1_outputs, p2_outputs = None, None
            self.ac.train(draws, phase1_outputs=p1_outputs, phase2_endings=p2_outputs)
            return {"success": True, "phase": 3, "predictor": "ac"}
        orch.register(PredictorEntry(
            predictor_id="ac",
            stage=STAGE_PHASE3,
            train_fn=_train_ac,
            cache_key="ac",
            depends_on=["endings"],
        ))

        # Stage 4
        def _train_sum(draws):
            from predictors.sum_predictor import SumPredictor
            if self.sum_pred is None:
                self.sum_pred = SumPredictor(feature_dim=self.feature_dim)
            try:
                p1_outputs = self.phase1.predict_all(draws)
                p2_outputs = self.endings.predict(draws, phase1_outputs=p1_outputs) if self.endings else None
                p3_outputs = self.ac.predict(
                    draws, phase1_outputs=p1_outputs, phase2_endings=p2_outputs
                ) if self.ac else None
            except Exception:
                p1_outputs, p2_outputs, p3_outputs = None, None, None
            self.sum_pred.train(
                draws,
                phase1_outputs=p1_outputs,
                phase2_endings=p2_outputs,
                phase3_ac=p3_outputs,
            )
            return {"success": True, "phase": 4, "predictor": "sum"}
        orch.register(PredictorEntry(
            predictor_id="sum",
            stage=STAGE_PHASE4,
            train_fn=_train_sum,
            cache_key="sum",
            depends_on=["ac"],
        ))


# ────────────────── CLI smoke ──────────────────


def main():
    import argparse

    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        rng = np.random.default_rng(config.RANDOM_SEED)
        # 가짜 100 회차 draws (최신순)
        draws = []
        for r in range(100, 0, -1):
            nums = sorted(rng.choice(45, size=6, replace=False) + 1)
            bonus = int(rng.integers(1, 46))
            while bonus in nums:
                bonus = int(rng.integers(1, 46))
            draws.append({"round": r, "numbers": list(nums), "bonus": bonus})

        pipeline = PredictorPipeline(feature_dim=24)
        print("\n[PredictorPipeline] training 4 phases (smoke)...")
        results = pipeline.train(draws, min_history=30)
        print(f"\n[PredictorPipeline] train results:")
        for phase, info in results.items():
            if phase == "wall_time_total":
                print(f"  {phase:15s} = {info:.2f}s")
            else:
                status = info.get("status", "unknown") if isinstance(info, dict) else info
                print(f"  {phase:15s} = {status}")

        print(f"\n[PredictorPipeline] full predict (smoke)...")
        out = pipeline.predict_all(draws[:30])
        for phase in ("phase1", "phase2", "phase3", "phase4"):
            v = out.get(phase, {})
            if isinstance(v, dict) and "error" in v:
                print(f"  {phase:10s} error: {v['error']}")
            elif isinstance(v, dict):
                print(f"  {phase:10s} = {len(v)} keys")
            else:
                print(f"  {phase:10s} = {type(v).__name__}")


if __name__ == "__main__":
    main()
