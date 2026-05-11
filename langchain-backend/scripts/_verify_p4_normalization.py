# -*- coding: utf-8 -*-
"""P4 정규화 + Ridge 가중치 로드 검증."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.consensus_analyzer import ConsensusAnalyzer
from models.number_scorer import NumberScorer

# 1. P4 0~1 정규화 검증
a = ConsensusAnalyzer()
rankings = {
    "m1": list(range(1, 46)),                      # 1, 2, 3, ... 45
    "m2": list(range(45, 0, -1)),                  # 45, 44, ..., 1
    "m3": [n for n in range(1, 46) if n % 2 == 1] + [n for n in range(2, 46, 2)],  # 홀수+짝수
}
metrics = a.compute_metrics(rankings)
scores = [metrics[n]["consensus_score"] for n in range(1, 46)]
raws   = [metrics[n]["consensus_score_raw"] for n in range(1, 46)]

print("[P4 normalization]")
print(f"  raw range:        [{min(raws):.2f}, {max(raws):.2f}]")
print(f"  normalized range: [{min(scores):.3f}, {max(scores):.3f}]  (expected: ~0.000 ~ 1.000)")
assert 0.0 <= min(scores) <= 0.001
assert 0.999 <= max(scores) <= 1.001
print("  PASS: 0~1 정규화 정상")

# 2. Ridge 가중치 로드 검증
print()
print("[Ridge weights load]")
scorer = NumberScorer()
print(f"  pillar_weights: {[round(w, 4) for w in scorer.pillar_weights]}")
print(f"  expected:       [0.312, 0.298, 0.245, 0.145]")
total = sum(scorer.pillar_weights)
print(f"  sum: {total:.4f}  (expected: 1.000)")
ok = (
    abs(scorer.pillar_weights[0] - 0.312) < 0.01
    and abs(scorer.pillar_weights[1] - 0.298) < 0.01
    and abs(scorer.pillar_weights[2] - 0.245) < 0.01
    and abs(scorer.pillar_weights[3] - 0.145) < 0.01
)
print(f"  {'PASS' if ok else 'FAIL'}: Stage 3-6 가중치 자동 로드")
