"""T-1: DAG 6 stage 학습 오케스트레이터.

Stage 0: 글로벌 인프라 (G-1~G-7 적용 + Markov 통합)
Stage 1: Phase 1 Predictor 16개 + 이월수 변형 1 = 17 인스턴스 학습
Stage 2: Phase 2 (Phase 1 캐시) — 끝수합
Stage 3: Phase 3 (Phase 1+2 캐시) — AC값
Stage 4: Phase 4 (Phase 1+2+3) — 총합
Stage 5: 메인 1~45 모델 (LSTM/CNN/Transformer/XGBoost/GNN/AE) — INPUT_DIM 동결
Stage 6: MetaLearner 부트스트랩 (task 가중치, alpha)

본 오케스트레이터는 *공통 인터페이스*만 정의. 21개 신규 predictor 구현은
별도 PR(Phase 1)에서 등록된다. 현 시점에서는 Stage 0/5/6만 실제 동작.

캐시 명세:
    saved_models/cache/phaseN/<predictor_id>_outputs.parquet
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable

import config


# ────────────────── Stage 정의 ──────────────────

STAGE_GLOBAL = 0
STAGE_PHASE1 = 1
STAGE_PHASE2 = 2
STAGE_PHASE3 = 3
STAGE_PHASE4 = 4
STAGE_MAIN_45 = 5
STAGE_META = 6

STAGE_NAMES = {
    STAGE_GLOBAL:  "Stage 0: 글로벌 인프라 (G-1~G-7 + Markov)",
    STAGE_PHASE1:  "Stage 1: Phase 1 Predictor (16 + 이월수 변형 1)",
    STAGE_PHASE2:  "Stage 2: Phase 2 (끝수합)",
    STAGE_PHASE3:  "Stage 3: Phase 3 (AC값)",
    STAGE_PHASE4:  "Stage 4: Phase 4 (총합)",
    STAGE_MAIN_45: "Stage 5: 메인 1~45 모델 (INPUT_DIM 동결)",
    STAGE_META:    "Stage 6: MetaLearner 부트스트랩",
}


# ────────────────── Predictor 등록 ──────────────────

@dataclass
class PredictorEntry:
    """Stage에 등록되는 predictor 단위."""

    predictor_id: str
    stage: int
    train_fn: Callable[[list], dict]   # train_fn(draws) → result dict
    cache_key: str                      # parquet 캐시 파일명 (predictor_id 기본)
    enabled: bool = True
    depends_on: list[str] = field(default_factory=list)  # 의존 predictor_id


# ────────────────── 오케스트레이터 ──────────────────

class TrainingOrchestrator:
    """DAG 6 stage 순차 실행 + 캐시 무결성 검증."""

    def __init__(self, save_dir: str | None = None):
        if save_dir is None:
            save_dir = os.path.join(config.MODEL_DIR, "cache")
        self.cache_dir = save_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        for stage_id in range(7):
            os.makedirs(self._stage_dir(stage_id), exist_ok=True)

        self._registry: dict[int, list[PredictorEntry]] = {i: [] for i in range(7)}

    # ── 등록 API ─────────────────────────────────────────────────────

    def register(self, entry: PredictorEntry) -> None:
        """Stage에 predictor를 등록."""
        if entry.stage not in self._registry:
            raise ValueError(f"Invalid stage: {entry.stage}")
        # 중복 등록 방지
        existing_ids = {e.predictor_id for e in self._registry[entry.stage]}
        if entry.predictor_id in existing_ids:
            raise ValueError(f"predictor_id '{entry.predictor_id}' already registered "
                             f"in stage {entry.stage}")
        self._registry[entry.stage].append(entry)

    def list_stage(self, stage_id: int) -> list[PredictorEntry]:
        return list(self._registry.get(stage_id, []))

    def all_predictor_ids(self) -> list[str]:
        out = []
        for entries in self._registry.values():
            out.extend(e.predictor_id for e in entries)
        return out

    # ── 캐시 경로 ────────────────────────────────────────────────────

    def _stage_dir(self, stage_id: int) -> str:
        return os.path.join(self.cache_dir, f"stage{stage_id}")

    def cache_path(self, stage_id: int, cache_key: str) -> str:
        """Stage N의 predictor cache 파일 경로 (parquet 또는 빈 marker)."""
        return os.path.join(self._stage_dir(stage_id), f"{cache_key}.parquet")

    def cache_marker_path(self, stage_id: int, cache_key: str) -> str:
        """Stage 완료 marker (parquet 미생성 가능 — Stage 0/5/6 학습 인프라 등)."""
        return os.path.join(self._stage_dir(stage_id), f"{cache_key}.done")

    # ── DAG 무결성 검증 ──────────────────────────────────────────────

    def validate_dag(self, up_to_stage: int = STAGE_META) -> dict:
        """Stage 0..up_to_stage의 캐시·marker 무결성 검증.

        Returns:
            {ok, missing: [(stage, cache_key)], total_required, found}
        """
        missing = []
        total = 0
        found = 0
        for stage_id in range(0, up_to_stage + 1):
            for entry in self._registry.get(stage_id, []):
                if not entry.enabled:
                    continue
                total += 1
                # parquet 또는 .done marker 존재 시 통과
                p1 = self.cache_path(stage_id, entry.cache_key)
                p2 = self.cache_marker_path(stage_id, entry.cache_key)
                if os.path.exists(p1) or os.path.exists(p2):
                    found += 1
                else:
                    missing.append((stage_id, entry.cache_key))
        return {
            "ok": len(missing) == 0,
            "missing": missing,
            "total_required": total,
            "found": found,
        }

    # ── 실행 ─────────────────────────────────────────────────────────

    def run_stage(self, stage_id: int, draws: list, fold_id: int = 0) -> dict:
        """1 stage 실행 — 모든 등록된 predictor 순차 학습.

        Returns:
            {stage, n_predictors, results: [{predictor_id, success, wall_time}], wall_time_total}
        """
        if stage_id not in self._registry:
            raise ValueError(f"Invalid stage: {stage_id}")

        entries = [e for e in self._registry[stage_id] if e.enabled]
        results = []
        t0 = time.time()

        for entry in entries:
            t_start = time.time()
            try:
                out = entry.train_fn(draws)
                success = bool(out.get("success", True)) if isinstance(out, dict) else True
                # marker 파일 생성 (parquet은 train_fn이 직접 생성한다고 가정)
                if success:
                    open(self.cache_marker_path(stage_id, entry.cache_key), "w").close()
            except Exception as e:
                print(f"  [Orchestrator] {entry.predictor_id} 실패: {e}")
                success = False
                out = {"success": False, "error": str(e)}
            wall = time.time() - t_start
            results.append({
                "predictor_id": entry.predictor_id,
                "success": success,
                "wall_time": wall,
                "result": out if isinstance(out, dict) else None,
            })

        return {
            "stage": stage_id,
            "stage_name": STAGE_NAMES.get(stage_id, ""),
            "fold_id": fold_id,
            "n_predictors": len(entries),
            "results": results,
            "wall_time_total": time.time() - t0,
        }

    def run_all_stages(self, draws: list, fold_id: int = 0) -> dict:
        """전체 6 stage 순차 실행. 이전 stage 실패 시 다음은 진행.

        DAG 위계:
            stage N의 모든 predictor 완료 후에만 N+1 진입 (validate_dag 검증)
        """
        all_results = []
        for stage_id in range(0, STAGE_META + 1):
            stage_result = self.run_stage(stage_id, draws, fold_id=fold_id)
            all_results.append(stage_result)
            # 의존 무결성 검증 — fail 시 경고만 (다음 stage 강행 X)
            check = self.validate_dag(up_to_stage=stage_id)
            stage_result["dag_check"] = check
            if not check["ok"]:
                print(f"  [Orchestrator] Stage {stage_id} 후 DAG 무결성 미달: "
                      f"{len(check['missing'])} predictor missing → "
                      f"다음 stage 진행하지만 의존 결손 위험")
        return {"all_stages": all_results}
