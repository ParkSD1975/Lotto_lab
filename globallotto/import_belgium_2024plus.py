"""
Belgium Lotto 2024-03-16 이후 데이터 → Supabase 추가 import
(기존 2002~2024-03-13 데이터는 유지하고, 새 날짜만 upsert)
"""

import csv, os, datetime
from supabase import create_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TODAY = datetime.date.today().isoformat()   # 오늘 날짜는 제외 (아직 추첨 전일 수 있음)
BATCH_SIZE = 100

def calc_stats(nums):
    s = sorted(nums)
    total = sum(s)
    tail_sum = sum(n % 10 for n in s)
    odd_count = sum(1 for n in s if n % 2 == 1)
    even_count = 6 - odd_count
    low_count = sum(1 for n in s if n <= 22)
    high_count = 6 - low_count
    consec = sum(1 for i in range(len(s)-1) if s[i+1] - s[i] == 1)
    diffs = [s[i+1] - s[i] for i in range(len(s)-1)]
    ac = len(set(diffs)) - 1
    return {
        "sum": total, "tail_sum": tail_sum, "ac": ac,
        "odd_count": odd_count, "even_count": even_count,
        "low_count": low_count, "high_count": high_count,
        "consecutive_pairs": consec,
    }

def main():
    # lottery_id 조회
    res = supabase.table("lotteries").select("id").eq("name", "Belgium Lotto").single().execute()
    lottery_id = res.data["id"]
    print(f"Belgium Lotto id: {lottery_id}")

    # CSV 로드
    path = os.path.join(BASE_DIR, "Belgium_Lotto_2024plus.csv")
    batch = []
    inserted = 0
    skipped = 0

    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            draw_date = row["date"]

            # 오늘 날짜 제외 (추첨 전일 가능성)
            if draw_date >= TODAY:
                print(f"  [SKIP] {draw_date} >= 오늘({TODAY}), 제외")
                skipped += 1
                continue

            try:
                n = [int(row["n1"]), int(row["n2"]), int(row["n3"]),
                     int(row["n4"]), int(row["n5"]), int(row["n6"])]
                bonus = int(row["bonus"]) if row.get("bonus") else None

                stats = calc_stats(n)
                record = {
                    "lottery_id": lottery_id,
                    "draw_date": draw_date,
                    "n1": n[0], "n2": n[1], "n3": n[2],
                    "n4": n[3], "n5": n[4], "n6": n[5],
                    "b1": bonus,
                    **stats,
                }
                batch.append(record)

                if len(batch) >= BATCH_SIZE:
                    supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
                    inserted += len(batch)
                    print(f"  {inserted}건 업로드...")
                    batch = []

            except Exception as e:
                print(f"  [ERR] {row}: {e}")
                skipped += 1

    if batch:
        supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
        inserted += len(batch)

    print(f"\n✓ Belgium Lotto 2024+ → {inserted}건 삽입 / {skipped}건 스킵")

    # 최종 확인
    res2 = supabase.table("draws").select("draw_date", count="exact") \
        .eq("lottery_id", lottery_id).execute()
    print(f"  Belgium Lotto 전체 건수: {res2.count}건")
    print(f"  최신 날짜: {max(r['draw_date'] for r in res2.data)}")

if __name__ == "__main__":
    main()
