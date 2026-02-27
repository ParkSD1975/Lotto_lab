"""
lotto-filter-api / main.py (Optimized for Free Tier)
Memory usage reduced from ~1GB to < 200MB.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
from itertools import combinations
import time

app = FastAPI(title="Lotto Filter Count API (Free Tier)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── Optimized Data Structures ──────────────────────────────────────
# Memory: combos(48MB) + sums(16MB) + acs(8MB) = ~72MB baseline
combos = None  # shape: (8145060, 6) uint8
sums = None    # shape: (8145060,) uint16
acs = None     # shape: (8145060,) uint8

def calc_ac_single(nums):
    nums_sorted = sorted(nums)
    diffs = set()
    for i in range(len(nums_sorted)):
        for j in range(i+1, len(nums_sorted)):
            diffs.add(nums_sorted[j] - nums_sorted[i])
    return len(diffs) - 5

def build_data():
    global combos, sums, acs
    print("🔨 Building memory-efficient data structures...")
    t0 = time.time()

    N = 8145060
    # Fill numpy array row-by-row: avoids ~650MB intermediate Python list
    combos = np.empty((N, 6), dtype=np.uint8)
    for i, c in enumerate(combinations(range(1, 46), 6)):
        combos[i] = c

    # Pre-calculate Sums (very common)
    sums = combos.sum(axis=1).astype(np.uint16)

    # Pre-calculate AC using chunked vectorization: avoids 8M-item Python list
    print("🔨 Pre-calculating AC values...")
    acs = np.empty(N, dtype=np.uint8)
    CHUNK = 500_000
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]  # 15 pairs

    for start in range(0, N, CHUNK):
        end = min(start + CHUNK, N)
        chunk = combos[start:end]
        cs = end - start
        diff_flags = np.zeros((cs, 44), dtype=bool)
        idx = np.arange(cs)
        for i, j in pairs:
            d = chunk[:, j].astype(np.int32) - chunk[:, i].astype(np.int32) - 1
            diff_flags[idx, d] = True
        acs[start:end] = diff_flags.sum(axis=1, dtype=np.uint8) - 5

    elapsed = time.time() - t0
    print(f"✅ Data ready in {elapsed:.1f}s. Memory base: ~72MB")

@app.on_event("startup")
def startup_event():
    build_data()

# ── Request Model ──────────────────────────────────────────────────
class FilterRequest(BaseModel):
    fixed: list[int] = []
    excluded: list[int] = []
    total_sum_enabled: bool = False
    total_sum_min: int = 21
    total_sum_max: int = 255
    total_sum_excluded: list[int] = []
    last_digit_sum_enabled: bool = False
    last_digit_sum_min: int = 0
    last_digit_sum_max: int = 54
    last_digit_sum_excluded: list[int] = []
    ac_value_enabled: bool = False
    ac_value_min: int = 0
    ac_value_max: int = 10
    odd_even_enabled: bool = False
    odd_even_counts: list[int] = []
    high_low_enabled: bool = False
    high_low_counts: list[int] = []
    prime_enabled: bool = False
    prime_counts: list[int] = []
    composite_enabled: bool = False
    composite_counts: list[int] = []
    tail_digit_enabled: bool = False
    tail_digit_filters: dict = {} # {"0": {"min":0, "max":6}, ...}
    band_enabled: bool = False
    band_filters: dict = {} # {"1_10": {"min":0,"max":6}, "11_20": {...}, ...} (단번대/10번대/...)

@app.post("/api/count")
def count_combos(req: FilterRequest):
    if combos is None:
        return {"count": 0, "error": "Initializing..."}
    
    mask = np.ones(len(combos), dtype=bool)
    
    # 1. Fixed / Excluded
    if req.fixed:
        for val in req.fixed:
            mask &= np.any(combos == val, axis=1)
    if req.excluded:
        for val in req.excluded:
            mask &= ~np.any(combos == val, axis=1)
            
    # 2. Total Sum
    if req.total_sum_enabled:
        mask &= (sums >= req.total_sum_min) & (sums <= req.total_sum_max)
        if req.total_sum_excluded:
            mask &= ~np.isin(sums, np.array(req.total_sum_excluded, dtype=np.uint16))
            
    # 3. Tail Sum (calculate on the fly: 8M * 6 -> fast enough)
    if req.last_digit_sum_enabled:
        tsums = (combos % 10).sum(axis=1)
        mask &= (tsums >= req.last_digit_sum_min) & (tsums <= req.last_digit_sum_max)
        if req.last_digit_sum_excluded:
            mask &= ~np.isin(tsums, np.array(req.last_digit_sum_excluded, dtype=np.uint8))
            
    # 4. AC Value
    if req.ac_value_enabled:
        mask &= (acs >= req.ac_value_min) & (acs <= req.ac_value_max)
        
    # 5. Odd/Even
    if req.odd_even_enabled and req.odd_even_counts:
        odds = (combos % 2 == 1).sum(axis=1)
        mask &= np.isin(odds, np.array(req.odd_even_counts, dtype=np.uint8))
        
    # 6. High/Low (23~45)
    if req.high_low_enabled and req.high_low_counts:
        highs = (combos >= 23).sum(axis=1)
        mask &= np.isin(highs, np.array(req.high_low_counts, dtype=np.uint8))
        
    # 7. Prime Numbers
    if req.prime_enabled and req.prime_counts:
        primes_set = {2,3,5,7,11,13,17,19,23,29,31,37,41,43}
        is_prime = np.isin(combos, list(primes_set))
        p_counts = is_prime.sum(axis=1)
        mask &= np.isin(p_counts, np.array(req.prime_counts, dtype=np.uint8))

    # 8. Composite Numbers
    if req.composite_enabled and req.composite_counts:
        comp_set = {4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,32,33,34,35,36,38,39,40,42,44,45}
        is_comp = np.isin(combos, list(comp_set))
        c_counts = is_comp.sum(axis=1)
        mask &= np.isin(c_counts, np.array(req.composite_counts, dtype=np.uint8))

    # 9. Tail Digits
    if req.tail_digit_enabled and req.tail_digit_filters:
        tails = combos % 10
        for d_str, rng in req.tail_digit_filters.items():
            d = int(d_str)
            d_count = (tails == d).sum(axis=1)
            mask &= (d_count >= rng.get("min",0)) & (d_count <= rng.get("max",6))

    # 10. Number Range (Band) Filter – 번호대별 패턴
    # 키: "1_10"(단번대), "11_20"(10번대), "21_30"(20번대), "31_40"(30번대), "41_45"(40번대)
    # 한글 키도 호환 지원
    if req.band_enabled and req.band_filters:
        BAND_RANGES = {
            "1_10":  (1,  10),   # 단번대 (1~10)
            "11_20": (11, 20),   # 10번대 (11~20)
            "21_30": (21, 30),   # 20번대 (21~30)
            "31_40": (31, 40),   # 30번대 (31~40)
            "41_45": (41, 45),   # 40번대 (41~45)
            # 한글 키 호환
            "단번대": (1,  10),
            "10번대": (11, 20),
            "20번대": (21, 30),
            "30번대": (31, 40),
            "40번대": (41, 45),
        }
        for band_key, rng in req.band_filters.items():
            if band_key == "entropy":
                continue  # 엔트로피는 현재 미지원 (skip)
            band_range = BAND_RANGES.get(band_key)
            if not band_range:
                continue
            lo, hi = band_range
            band_count = ((combos >= lo) & (combos <= hi)).sum(axis=1)
            mask &= (band_count >= rng.get("min", 0)) & (band_count <= rng.get("max", 6))

    count = int(np.sum(mask))
    return {"count": count}

@app.get("/api/health")
def health():
    return {"status": "ready" if combos is not None else "loading"}
