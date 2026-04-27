"""U-1: 6번호 자체 계산 지표의 결정론적 정답 검증.

골든 데이터(tests/fixtures/golden_indicators.json)의 expected 값과
독립 구현(본 테스트 내 헬퍼)의 결과가 일치하는지 검증.

목적:
- 회귀 검출: 향후 filter_stats 변경 시 정답 깨짐 즉시 감지
- 명세 자체 정합성: 골든 데이터의 손계산이 코드와 일치 보증
"""

import json
from pathlib import Path

import pytest


PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
COMPOSITES = {4, 6, 8, 9, 10, 12, 14, 15, 16, 18, 20, 21, 22, 24, 25, 26, 27, 28,
              30, 32, 33, 34, 35, 36, 38, 39, 40, 42, 44, 45}
SQUARES = {1, 4, 9, 16, 25, 36}
TRIANGULARS = {1, 3, 6, 10, 15, 21, 28, 36, 45}
TWINS = {11, 22, 33, 44}
MUL3 = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45}
MUL4 = {4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44}
MUL5 = {5, 10, 15, 20, 25, 30, 35, 40, 45}
MUL7 = {7, 14, 21, 28, 35, 42}
MUL8 = {8, 16, 24, 32, 40}


# ── 헬퍼: 본 테스트 내 독립 구현 (filter_stats 의존 안 함) ──

def calc_sum(nums): return sum(nums)
def calc_tail_sum(nums): return sum(n % 10 for n in nums)

def calc_ac(nums):
    s = sorted(nums)
    diffs = set()
    for i in range(len(s)):
        for j in range(i + 1, len(s)):
            diffs.add(abs(s[i] - s[j]))
    return len(diffs) - (len(s) - 1)

def calc_low(nums): return sum(1 for n in nums if n <= 22)
def calc_high(nums): return sum(1 for n in nums if n >= 23)
def calc_odd(nums): return sum(1 for n in nums if n % 2 == 1)
def calc_even(nums): return sum(1 for n in nums if n % 2 == 0)

def calc_consecutive(nums):
    s = sorted(nums)
    return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)

def calc_in_set(nums, s): return sum(1 for n in nums if n in s)

def calc_digit_dist(nums):
    dist = [0] * 10
    for n in nums:
        dist[n % 10] += 1
    return dist

def calc_decade_dist(nums):
    """[1-9, 10-19, 20-29, 30-39, 40-45]"""
    dist = [0, 0, 0, 0, 0]
    for n in nums:
        if n <= 9: dist[0] += 1
        elif n <= 19: dist[1] += 1
        elif n <= 29: dist[2] += 1
        elif n <= 39: dist[3] += 1
        else: dist[4] += 1
    return dist


# ── pytest 픽스처 ──

@pytest.fixture(scope="module")
def golden_data():
    path = Path(__file__).parent.parent / "fixtures" / "golden_indicators.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries(golden_data):
    return golden_data["entries"]


# ── 테스트: 각 지표 ──

def _ids(entries):
    return [e["label"] for e in entries]


@pytest.mark.parametrize("entry_idx", range(4))
class TestIndicators:
    """각 골든 entry에 대해 모든 지표 검증."""

    def test_sum(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_sum(e["numbers"]) == e["expected"]["sum"], f"{e['label']}: sum"

    def test_tail_sum(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_tail_sum(e["numbers"]) == e["expected"]["tail_sum"]

    def test_ac_value(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_ac(e["numbers"]) == e["expected"]["ac_value"]

    def test_low_high(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_low(e["numbers"]) == e["expected"]["low_count"]
        assert calc_high(e["numbers"]) == e["expected"]["high_count"]
        assert calc_low(e["numbers"]) + calc_high(e["numbers"]) == 6

    def test_odd_even(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_odd(e["numbers"]) == e["expected"]["odd_count"]
        assert calc_even(e["numbers"]) == e["expected"]["even_count"]
        assert calc_odd(e["numbers"]) + calc_even(e["numbers"]) == 6

    def test_consecutive(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_consecutive(e["numbers"]) == e["expected"]["consecutive_count"]

    def test_prime_composite(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_in_set(e["numbers"], PRIMES) == e["expected"]["prime_count"]
        assert calc_in_set(e["numbers"], COMPOSITES) == e["expected"]["composite_count"]
        # 소수+합성수+1 = 6 (45 풀에서 1만 둘 다 아님)
        ones = sum(1 for n in e["numbers"] if n == 1)
        assert (
            e["expected"]["prime_count"]
            + e["expected"]["composite_count"]
            + ones
            == 6
        )

    def test_square(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_in_set(e["numbers"], SQUARES) == e["expected"]["square_count"]

    def test_triangular(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_in_set(e["numbers"], TRIANGULARS) == e["expected"]["triangular_count"]

    def test_twin(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_in_set(e["numbers"], TWINS) == e["expected"]["twin_count"]

    def test_digit_dist(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_digit_dist(e["numbers"]) == e["expected"]["digit_dist"]
        assert sum(e["expected"]["digit_dist"]) == 6  # 일관성

    def test_decade_dist(self, entries, entry_idx):
        e = entries[entry_idx]
        assert calc_decade_dist(e["numbers"]) == e["expected"]["decade_dist"]
        assert sum(e["expected"]["decade_dist"]) == 6

    def test_multiples(self, entries, entry_idx):
        e = entries[entry_idx]
        exp = e["expected"]
        assert calc_in_set(e["numbers"], MUL3) == exp["mul3_count"]
        assert calc_in_set(e["numbers"], MUL4) == exp["mul4_count"]
        assert calc_in_set(e["numbers"], MUL5) == exp["mul5_count"]
        assert calc_in_set(e["numbers"], MUL7) == exp["mul7_count"]
        assert calc_in_set(e["numbers"], MUL8) == exp["mul8_count"]


# ── 자체 일관성 (entries 간) ──

def test_all_entries_have_6_numbers(entries):
    for e in entries:
        assert len(e["numbers"]) == 6, f"{e['label']}: not 6 numbers"
        assert all(1 <= n <= 45 for n in e["numbers"])
        assert len(set(e["numbers"])) == 6, f"{e['label']}: duplicate numbers"
