"""Croatia Loto 6/45 실제 데이터 → Supabase import"""
import csv, os
from supabase import create_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"
LOTTERY_NAME = "Loto 6/45"
BATCH_SIZE = 100

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def calc_stats(nums):
    s = sorted(nums)
    diffs = [s[i+1]-s[i] for i in range(len(s)-1)]
    return {
        "sum": sum(s),
        "tail_sum": sum(n%10 for n in s),
        "ac": len(set(diffs))-1,
        "odd_count": sum(1 for n in s if n%2==1),
        "even_count": sum(1 for n in s if n%2==0),
        "low_count": sum(1 for n in s if n<=22),
        "high_count": sum(1 for n in s if n>22),
        "consecutive_pairs": sum(1 for i in range(len(s)-1) if s[i+1]-s[i]==1),
    }

def main():
    res = supabase.table("lotteries").select("id").eq("name", LOTTERY_NAME).single().execute()
    lottery_id = res.data["id"]
    print(f"{LOTTERY_NAME} id: {lottery_id}")

    supabase.table("draws").delete().eq("lottery_id", lottery_id).execute()
    print("기존 데이터 삭제 완료")

    batch, inserted = [], 0
    with open(os.path.join(BASE_DIR, "Croatia_Loto_real.csv"), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            nums = [int(row[f"n{i}"]) for i in range(1,7)]
            bonus = int(row["bonus"]) if row.get("bonus") and str(row["bonus"]).isdigit() else None
            batch.append({
                "lottery_id": lottery_id,
                "draw_date": row["date"],
                "n1":nums[0],"n2":nums[1],"n3":nums[2],
                "n4":nums[3],"n5":nums[4],"n6":nums[5],
                "b1": bonus,
                **calc_stats(nums),
            })
            if len(batch) >= BATCH_SIZE:
                supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
                inserted += len(batch); batch = []
                print(f"  {inserted}건...")

    if batch:
        supabase.table("draws").upsert(batch, on_conflict="lottery_id,draw_date").execute()
        inserted += len(batch)

    res2 = supabase.table("draws").select("draw_date",count="exact").eq("lottery_id",lottery_id).execute()
    print(f"✓ {inserted}건 삽입  |  전체 {res2.count}건")

if __name__ == "__main__":
    main()
