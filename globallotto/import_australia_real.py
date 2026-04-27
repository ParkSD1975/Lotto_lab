"""
Australia Saturday/Monday/Wednesday Lotto 실제 데이터 → Supabase import
기존 가짜 데이터를 삭제하고 실제 데이터로 교체
"""

import csv, os, datetime
from supabase import create_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FILES = [
    ("Saturday_Lotto_real.csv",   "Saturday Lotto"),
    ("Monday_Lotto_real.csv",     "Monday Lotto"),
    ("Wednesday_Lotto_real.csv",  "Wednesday Lotto"),
]

BATCH_SIZE = 200

def get_lottery_id(name: str) -> str:
    res = supabase.table("lotteries").select("id").eq("name", name).single().execute()
    return res.data["id"]

def calc_stats(nums: list[int]) -> dict:
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
        "sum": total,
        "tail_sum": tail_sum,
        "ac": ac,
        "odd_count": odd_count,
        "even_count": even_count,
        "low_count": low_count,
        "high_count": high_count,
        "consecutive_pairs": consec,
    }

def load_csv(filename: str) -> list[dict]:
    path = os.path.join(BASE_DIR, filename)
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def import_lottery(csv_file: str, lottery_name: str):
    print(f"\n── {lottery_name} ({csv_file}) ──")

    # lottery_id 조회
    lottery_id = get_lottery_id(lottery_name)
    print(f"  lottery_id: {lottery_id}")

    # 기존 가짜 데이터 삭제
    del_res = supabase.table("draws").delete().eq("lottery_id", lottery_id).execute()
    print(f"  기존 데이터 삭제 완료")

    # CSV 로드
    rows = load_csv(csv_file)
    if not rows:
        print(f"  [WARN] CSV가 비어있습니다")
        return

    batch = []
    inserted = 0
    skipped = 0

    for row in rows:
        try:
            draw_date = row["date"]
            n = [int(row["n1"]), int(row["n2"]), int(row["n3"]),
                 int(row["n4"]), int(row["n5"]), int(row["n6"])]
            supp1 = int(row["supp1"]) if row.get("supp1") else None
            supp2 = int(row["supp2"]) if row.get("supp2") else None

            stats = calc_stats(n)
            record = {
                "lottery_id": lottery_id,
                "draw_date": draw_date,
                "n1": n[0], "n2": n[1], "n3": n[2],
                "n4": n[3], "n5": n[4], "n6": n[5],
                "b1": supp1,
                "b2": supp2,
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

    print(f"  ✓ {inserted}건 삽입 / {skipped}건 스킵")

def main():
    for csv_file, lottery_name in FILES:
        import_lottery(csv_file, lottery_name)

    print("\n=== 완료 ===")
    # 결과 확인
    res = supabase.table("draws").select("lottery_id, draw_date", count="exact").execute()
    print("draws 테이블 총:", res.count)

if __name__ == "__main__":
    main()
