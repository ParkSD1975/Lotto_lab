"""11 base 모델 XAI 출력 통합기.

Master Plan Stage 4-A. 각 base wrapper의 XAI 메서드 호출 후 표준 dict로 통합.
NumberXAIExplainer가 이 출력을 받아 Layer 1/2/3 narrative 합성.

11 base XAI 출력:
  XGBoost/CatBoost: TreeSHAP top-K
  TabNet: Sparsemax attention mask
  CNN: Grad-CAM (그리드 입력만)
  GNN: Attention weights (인접 번호)
  Markov: 전이행렬 row
  AE: 재구성 오차
  TFT: Variable selection top-K
  N-BEATS: trend/seasonality/residual decomposition
  MHN: top-K similar past rounds
  Bayesian NN: sigma
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np


class XAIAggregator:
    """11 base 모델 XAI 통합기. 각 모델 wrapper의 XAI 메서드 graceful 호출."""

    def __init__(self, models: Optional[dict] = None):
        """models = {model_name: instance} — 11 base 일부만 가능 (None graceful)."""
        self.models = models or {}

    # ────── per-model XAI 추출 ──────

    def _xgb_shap(self, model, x: np.ndarray, top_k: int = 5) -> dict:
        try:
            shap = model.tree_shap(x) if hasattr(model, "tree_shap") else None
            if shap is None:
                # XGBoost 표준 model — feature_importance fallback
                if hasattr(model, "feature_importance"):
                    fi = model.feature_importance()
                    return {"feature_importance_top": _top_k_dict(fi, top_k)}
                return {}
            # shap shape (1, num_features) or (1, num_classes, num_features)
            arr = np.asarray(shap)
            if arr.ndim == 3:
                arr = arr.mean(axis=1)
            return {"shap_top": _top_k_indices(arr[0], top_k)}
        except Exception:
            return {}

    def _catboost_shap(self, model, x: np.ndarray, top_k: int = 5) -> dict:
        try:
            if hasattr(model, "tree_shap"):
                shap = model.tree_shap(x)
                arr = np.asarray(shap)
                if arr.ndim == 3:
                    arr = arr.mean(axis=1)
                return {"shap_top": _top_k_indices(arr[0], top_k)}
            return {}
        except Exception:
            return {}

    def _tabnet_attention(self, model, x: np.ndarray, top_k: int = 5) -> dict:
        try:
            if hasattr(model, "explain"):
                ex = model.explain(x)
                mask = ex.get("attention_mask")
                if mask is not None:
                    return {
                        "attention_mask_top": _top_k_indices(np.asarray(mask)[0], top_k),
                    }
            return {}
        except Exception:
            return {}

    def _cnn_grad_cam(self, model, x: np.ndarray) -> dict:
        # CNN Grad-CAM은 별도 구현 필요. wrapper에 없으면 skip.
        try:
            if hasattr(model, "grad_cam"):
                cam = model.grad_cam(x)
                return {"grad_cam_grid": np.asarray(cam).tolist()}
            return {}
        except Exception:
            return {}

    def _gnn_attention(self, model, target_number: int, top_k: int = 5) -> dict:
        try:
            if hasattr(model, "predict_edge_prob"):
                edges = model.predict_edge_prob()
                # target_number의 인접 번호 attention 정렬
                neighbors = []
                for (a, b), p in edges.items():
                    if a == target_number or b == target_number:
                        other = b if a == target_number else a
                        neighbors.append({"neighbor": int(other), "weight": float(p)})
                neighbors.sort(key=lambda d: -d["weight"])
                return {"attention_weights_top": neighbors[:top_k]}
            return {}
        except Exception:
            return {}

    def _markov_transition(self, model, last_state: int = 0) -> dict:
        try:
            if hasattr(model, "transition") or hasattr(model, "transition_matrix"):
                T = getattr(model, "transition", None) or getattr(model, "transition_matrix", None)
                if T is not None:
                    arr = np.asarray(T)
                    if 0 <= last_state < arr.shape[0]:
                        return {"transition_row": arr[last_state].tolist()}
            return {}
        except Exception:
            return {}

    def _ae_recon_error(self, model, x: np.ndarray) -> dict:
        try:
            if hasattr(model, "reconstruction_error"):
                err = model.reconstruction_error(x)
                return {"reconstruction_error": float(np.asarray(err).mean())}
            if hasattr(model, "anomaly_score"):
                err = model.anomaly_score(x)
                return {"reconstruction_error": float(np.asarray(err).mean())}
            return {}
        except Exception:
            return {}

    def _tft_variable_selection(self, model, x: np.ndarray, top_k: int = 5) -> dict:
        try:
            if hasattr(model, "explain"):
                ex = model.explain(x)
                vsn = ex.get("variable_selection_weights")
                if vsn is not None:
                    return {"variable_selection_top": _top_k_indices(np.asarray(vsn).flatten(), top_k)}
            return {}
        except Exception:
            return {}

    def _nbeats_decomposition(self, model, series: np.ndarray) -> dict:
        try:
            if hasattr(model, "decompose"):
                dec = model.decompose(series)
                return {
                    "decomposition": {
                        "trend": _safe_list(dec.get("trend")),
                        "seasonality": _safe_list(dec.get("seasonality")),
                        "residual": _safe_list(dec.get("residual")),
                    }
                }
            return {}
        except Exception:
            return {}

    def _mhn_similar(self, model, query: np.ndarray, top_k: int = 3) -> dict:
        try:
            if hasattr(model, "retrieve"):
                ret = model.retrieve(query, top_k=top_k)
                return {
                    "top_k_similar_rounds": [
                        {"round_idx": int(i), "similarity": float(s)}
                        for i, s in zip(
                            ret.get("top_k_indices", [])[:top_k],
                            ret.get("similarities", [])[:top_k],
                        )
                    ]
                }
            return {}
        except Exception:
            return {}

    def _bayesian_sigma(self, model, x: np.ndarray, target_number: int) -> dict:
        try:
            if hasattr(model, "predict_with_uncertainty"):
                unc = model.predict_with_uncertainty(x)
                std = unc.get("std")
                if std is not None:
                    arr = np.asarray(std)
                    if arr.ndim >= 1 and 0 <= (target_number - 1) < arr.shape[-1]:
                        return {"sigma": float(arr.flatten()[target_number - 1])}
                    return {"sigma": float(arr.mean())}
            return {}
        except Exception:
            return {}

    # ────── 통합 ──────

    def aggregate_per_number(
        self,
        number: int,
        x: Optional[np.ndarray] = None,
        scalar_series: Optional[np.ndarray] = None,
        last_markov_state: int = 0,
    ) -> dict:
        """번호 1개에 대한 11 base XAI 통합."""
        out = {}

        if x is None:
            x = np.zeros((1, 1), dtype=np.float32)
        x_arr = np.asarray(x)
        if x_arr.ndim == 1:
            x_arr = x_arr.reshape(1, -1)

        for name, model in self.models.items():
            if model is None:
                continue
            if name == "xgboost":
                out["xgboost"] = self._xgb_shap(model, x_arr)
            elif name == "catboost":
                out["catboost"] = self._catboost_shap(model, x_arr)
            elif name == "tabnet":
                out["tabnet"] = self._tabnet_attention(model, x_arr)
            elif name == "cnn":
                out["cnn"] = self._cnn_grad_cam(model, x_arr)
            elif name == "gnn":
                out["gnn"] = self._gnn_attention(model, number)
            elif name == "markov":
                out["markov"] = self._markov_transition(model, last_markov_state)
            elif name in ("ae", "autoencoder"):
                out["autoencoder"] = self._ae_recon_error(model, x_arr)
            elif name == "tft":
                out["tft"] = self._tft_variable_selection(model, x_arr)
            elif name == "nbeats":
                if scalar_series is not None:
                    out["nbeats"] = self._nbeats_decomposition(model, scalar_series)
            elif name == "mhn":
                out["mhn"] = self._mhn_similar(model, x_arr.flatten())
            elif name == "bayesian_nn":
                out["bayesian_nn"] = self._bayesian_sigma(model, x_arr, number)

        return out

    def aggregate_pillar_breakdown(
        self,
        number: int,
        scorer_metrics: Optional[dict] = None,
        recommender_evidence: Optional[dict] = None,
        consensus_metrics: Optional[dict] = None,
        filter_compliance: Optional[np.ndarray] = None,
    ) -> dict:
        """4 Pillar 분해 — NumberScorer/Recommender 출력 활용."""
        out = {}

        # Pillar 1: ensemble_prob
        ensemble_prob = None
        ci_lower = None
        if recommender_evidence:
            ensemble_prob = recommender_evidence.get("ensemble_prob") or recommender_evidence.get("score")
            ci_lower = recommender_evidence.get("ci_lower")
        out["pillar_1_ensemble_prob"] = {
            "value": float(ensemble_prob) if ensemble_prob is not None else None,
            "ci_lower": float(ci_lower) if ci_lower is not None else None,
        }

        # Pillar 2: filter_compliance
        comp_value = None
        passed = []
        failed = []
        if filter_compliance is not None and 1 <= number <= 45:
            arr = np.asarray(filter_compliance)
            if arr.shape[0] >= number:
                comp_value = float(arr[number - 1])
        if recommender_evidence:
            passed = recommender_evidence.get("passed_filters", []) or []
            failed = recommender_evidence.get("failed_filters", []) or []
        out["pillar_2_filter_compliance"] = {
            "value": comp_value,
            "passed_filters": passed,
            "failed_filters": failed,
        }

        # Pillar 3: individual_state
        out["pillar_3_individual_state"] = {
            "hotcold": (recommender_evidence or {}).get("hotcold"),
            "dormancy": (recommender_evidence or {}).get("dormancy"),
            "regression_top3_N": (recommender_evidence or {}).get("regression_top3_active_N"),
            "is_carryover_candidate": (recommender_evidence or {}).get("is_carryover_candidate", False),
        }

        # Pillar 4: consensus
        cons = None
        if consensus_metrics and number in consensus_metrics:
            m = consensus_metrics[number]
            cons = {
                "top10_count": int(m.get("top10_count", 0)),
                "bottom15_count": int(m.get("bottom15_count", 0)),
                "mean_rank": float(m.get("mean_rank", 0)),
                "std_rank": float(m.get("std_rank", 0)),
                "consensus_score": float(m.get("consensus_score", 0)),
            }
            cons["agreement_strength"] = _agreement_label(cons["std_rank"])
        out["pillar_4_consensus"] = cons or {}

        return out


# ────── helper ──────


def _top_k_indices(arr: np.ndarray, k: int) -> list[dict]:
    arr = np.asarray(arr).flatten()
    idx = np.argsort(-np.abs(arr))[:k]
    return [{"feature_idx": int(i), "value": float(arr[i])} for i in idx]


def _top_k_dict(d: dict, k: int) -> list[dict]:
    items = sorted(d.items(), key=lambda kv: -abs(kv[1]))[:k]
    return [{"feature": str(name), "value": float(v)} for name, v in items]


def _safe_list(arr) -> list:
    if arr is None:
        return []
    try:
        return np.asarray(arr).flatten().tolist()
    except Exception:
        return []


def _agreement_label(std_rank: float) -> str:
    if std_rank < 3:
        return "강"
    if std_rank < 7:
        return "중"
    return "약"


def main():
    """smoke."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        agg = XAIAggregator(models={"xgboost": None, "catboost": None, "tabnet": None})
        out = agg.aggregate_per_number(
            number=23,
            x=np.zeros((1, 65), dtype=np.float32),
        )
        print(f"[xai_aggregator] smoke: {len(out)} models aggregated")
        print(f"  None models gracefully skipped: {[k for k, v in out.items() if v == {}]}")

        pillar = agg.aggregate_pillar_breakdown(
            number=23,
            consensus_metrics={
                23: {"top10_count": 7, "bottom15_count": 0, "mean_rank": 5.2,
                     "std_rank": 2.8, "consensus_score": -3.6}
            },
        )
        print(f"[xai_aggregator] pillar breakdown keys: {list(pillar.keys())}")
        print(f"  pillar_4 agreement: {pillar['pillar_4_consensus'].get('agreement_strength')}")


if __name__ == "__main__":
    main()
