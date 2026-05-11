"""1223회차 실제값 확인."""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.supabase_client import fetch_all_draws
from predictors.phase3_ac import _compute_ac


def compute_endings_sum(numbers: list[int]) -> int:
    return sum(int(n) % 10 for n in numbers)


all_draws = fetch_all_draws()
target = [d for d in all_draws if int(d.get("round", 0)) == 1223]

if target:
    nums = target[0].get("numbers", [])
    print(f"1223회차 번호: {nums}")
    print(f"끝수합: {compute_endings_sum(nums)}")
    print(f"AC값: {_compute_ac(nums)}")
else:
    print("1223회차 없음 (아직 추첨 전)")
