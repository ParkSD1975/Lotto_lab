"""
Hungary Hatoslottó 공식 CSV → Supabase import
Source: https://bet.szerencsejatek.hu/cmsfiles/hatos.csv

CSV 구조 (헤더 없음, ';' 구분자):
  col[0] : Year
  col[1] : WeekNo
  col[2] : DayName (HU)
  col[3] : DrawDate  "2026.04.19."
  col[4~13]: 상금 정보 (무시)
  col[14]: Num1
  col[15]: Num2
  col[16]: Num3
  col[17]: Num4
  col[18]: Num5
  col[19]: Num6
"""

import csv, io, os, datetime, requests
from supabase import create_client

SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"
LOTTERY_NAME = "Hatoslottó"
BATCH_SIZE = 200

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def calc_stats(nums):
    s = sorted(nums)
    total = sum(s)
    tail_sum = sum(n % 10 for n in s)
    odd_count = sum(1 for n in s if n % 2 == 1)
    low_count = sum(1 for n in s if n <= 22)
    consec = sum(1 for i in range(len(s)-1) if s[i+1] - s[i] == 1)
    diffs = [s[i+1] - s[i] for i in range(len(s)-1)]
    ac = len(set(diffs)) - 1
    return {
        "sum": total,
        "tail_sum": tail_sum,
        "ac": ac,
        "odd_count": odd_count,
        "even_count": 6 - odd_count,
        "low_count": low_count,
        "high_count": 6 - low_count,
        "consecutive_pairs": consec,
    }

def parse_date(s: str):
    """'2026.04.19.' → '2026-04-19'"""
    s = s.strip().rstrip(".")
    parts = s.split(".")
    if len(parts) == 3:
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    return None

def main():
    # 1. CSV 다운로드
    print("CSV 다운로드 중...")
    r = requests.get("https://bet.szerencsejatek.hu/cmsfiles/hatos.csv", timeout=30)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")

    # 2. 파싱
    rows_data = []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    for row in reader:
        if len(row) < 20:
            continue
        draw_date_str = parse_date(row[3])
        if not draw_date_str:
            continue
        try:
            nums = [int(row[14]), int(row[15]), int(row[16]),
                    int(row[17]), int(row[18]), int(row[19])]
        except (ValueError, IndexError):
            continue
        rows_data.append({"date": draw_date_str, "nums": nums})

    print(f"파싱 완료: {len(rows_data)}건  ({rows_data[-1]['date']} ~ {rows_data[0]['date']})")

    # 3. lottery_id 조회
    res = supabase.table("lotteries").select("id").eq("name", LOTTERY_NAME).single().execute()
    lottery_id = res.data["id"]
    print(f"lottery_id: {lottery_id}")

    # 4. 기존 가짜 데이터 삭제
    supabase.table("draws").delete().eq("lottery_id", lottery_id).execute()
    print("기존 데이터 삭제 완료")

    # 5. Batch upsert
    batch = []
    inserted = 0

    for row in rows_data:
        stats = calc_stats(row["nums"])
        record = {
            "lottery_id": lottery_id,
            "draw_date": row["date"],
            "n1": row["nums"][0], "n2": row["nums"][1], "n3": row["nums"][2],
            "n4": row["nums"][3], "n5": row["nums"][4], "n6": row["nums"][5],
            **stats,
        }
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
            inserted += len(batch)
            print(f"  {inserted}건 업로드...")
            batch = []

    if batch:
        supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
        inserted += len(batch)

    print(f"\n✓ Hatoslottó → {inserted}건 삽입")

    # 6. 확인
    res2 = supabase.table("draws").select("draw_date", count="exact").eq("lottery_id", lottery_id).execute()
    dates = [r["draw_date"] for r in res2.data]
    print(f"  최종 건수: {res2.count}건  ({min(dates)} ~ {max(dates)})")

if __name__ == "__main__":
    main()
