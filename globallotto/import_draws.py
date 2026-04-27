"""
해외로또 CSV → Supabase draws 테이블 요일별 bulk import
Usage: python -X utf8 import_draws.py
"""

import csv, os, datetime
from supabase import create_client

SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"

# 요일(weekday) → lottery name 매핑 (0=월 1=화 2=수 3=목 4=금 5=토 6=일)
DOW_TO_LOTTERY = {
    0: "Mega 645 (월)",
    2: "Mega 645 (수)",
    4: "Mega 645 (금)",
    6: "Mega 645 (일)",
}

# CSV 파일 목록 (추가 시 여기에 등록)
CSV_FILES = [
    "Mega_Lotto_6_45.csv",
]

# ─────────────── 지표 계산 ───────────────
def calc_sum(nums):      return sum(nums)
def calc_tail_sum(nums): return sum(n % 10 for n in nums)
def calc_ac(nums):
    diffs = set()
    s = sorted(nums)
    for i in range(len(s)):
        for j in range(i+1, len(s)):
            diffs.add(abs(s[i] - s[j]))
    return len(diffs) - 5
def calc_odd_even(nums):
    odd = sum(1 for n in nums if n % 2 != 0)
    return odd, 6 - odd
def calc_low_high(nums):
    low = sum(1 for n in nums if n <= 23)
    return low, 6 - low
def calc_consecutive(nums):
    s = sorted(nums)
    return sum(1 for i in range(len(s)-1) if s[i+1] == s[i]+1)

def build_row(lottery_id, draw_date, nums, draw_no=None, b1=None, b2=None):
    s = sorted(nums)
    odd, even = calc_odd_even(s)
    low, high = calc_low_high(s)
    return {
        "lottery_id": lottery_id,
        "draw_date":  draw_date,
        "draw_no":    draw_no,
        "n1": s[0], "n2": s[1], "n3": s[2],
        "n4": s[3], "n5": s[4], "n6": s[5],
        "b1": b1, "b2": b2,
        "sum":               calc_sum(s),
        "tail_sum":          calc_tail_sum(s),
        "ac":                calc_ac(s),
        "odd_count":         odd,
        "even_count":        even,
        "low_count":         low,
        "high_count":        high,
        "consecutive_pairs": calc_consecutive(s),
    }

# ─────────────── 메인 ───────────────
def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # lotteries 조회 → name→id 맵
    res = client.table("lotteries").select("id,name").execute()
    name_to_id = {r["name"]: r["id"] for r in res.data}
    print("로또 목록:", list(name_to_id.keys()))

    base_dir = os.path.dirname(os.path.abspath(__file__))

    for csv_file in CSV_FILES:
        path = os.path.join(base_dir, csv_file)
        if not os.path.exists(path):
            print(f"[SKIP] 파일 없음: {path}")
            continue

        print(f"\n[{csv_file}] 파싱 시작...")

        # 요일별 rows 분류
        buckets = {name: [] for name in DOW_TO_LOTTERY.values()}
        skip_dow = set()

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for line in reader:
                draw_date = line.get("추첨일", "").strip()
                if not draw_date:
                    continue
                try:
                    nums = [
                        int(line["당첨번호 1"]), int(line["2"]),
                        int(line["3"]),           int(line["4"]),
                        int(line["5"]),           int(line["6"]),
                    ]
                except (KeyError, ValueError) as e:
                    print(f"  [WARN] 파싱 오류: {line} → {e}")
                    continue

                dow = datetime.date.fromisoformat(draw_date).weekday()  # 0=월
                lottery_name = DOW_TO_LOTTERY.get(dow)
                if not lottery_name:
                    if dow not in skip_dow:
                        print(f"  [SKIP] 매핑 없는 요일 {dow}: {draw_date}")
                        skip_dow.add(dow)
                    continue

                lottery_id = name_to_id.get(lottery_name)
                if not lottery_id:
                    print(f"  [SKIP] DB에 없는 로또명: {lottery_name}")
                    continue

                draw_no = line.get("회차", "").strip()
                draw_no = int(draw_no) if draw_no.isdigit() else None

                buckets[lottery_name].append(
                    build_row(lottery_id, draw_date, nums, draw_no=draw_no)
                )

        # 요일별 업서트
        for lottery_name, rows in buckets.items():
            if not rows:
                print(f"  [{lottery_name}] 데이터 없음 — 건너뜀")
                continue
            print(f"  [{lottery_name}] {len(rows)}건 업서트 중...")
            CHUNK = 500
            for i in range(0, len(rows), CHUNK):
                chunk = rows[i:i+CHUNK]
                client.table("draws").upsert(
                    chunk, on_conflict="lottery_id,draw_date"
                ).execute()
                print(f"    [{i+len(chunk)}/{len(rows)}] 완료")
            print(f"  [{lottery_name}] 업서트 완료!")

    print("\n전체 완료.")

if __name__ == "__main__":
    main()
