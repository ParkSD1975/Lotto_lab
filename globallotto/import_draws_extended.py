"""
해외로또 CSV → Supabase draws 테이블 bulk import (다중 포맷 지원)
Usage: python -X utf8 import_draws_extended.py

지원 로또:
  - Mega Lotto 6/45 (PH): 요일별 분류 (월/수/금)
  - Austria Lotto 6/45 (AT): WED/SUN
  - Australia Lotteries (AU): SAT/MON/WED
  - Netherlands Lotto (NL): SAT/WED
  - Belgium Lotto (BE): WED/SAT
  - Hungary Hatoslottó (HU): THU/SUN
  - Croatia Loto 6/45 (HR): WED
"""

import csv, os, datetime, sys
from supabase import create_client

SUPABASE_URL = "https://dkcflmyoscudawleglzb.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"

# ─────────────── 로또별 설정 ───────────────
LOTTERY_CONFIGS = {
    "Mega_Lotto_6_45.csv": {
        "name": "Mega Lotto 6/45 (PH)",
        "lottery_type": "dow_based",  # 요일별 분류
        "dow_mapping": {
            0: "Mega 645 (월)",
            2: "Mega 645 (수)",
            4: "Mega 645 (금)",
        },
        "columns": {
            "date": "추첨일",
            "numbers": ["당첨번호 1", "2", "3", "4", "5", "6"],
            "bonus": None,
            "draw_no": "회차",
        },
    },
    "Austria_Lotto_6_45.csv": {
        "name": "Austria Lotto 6/45",
        "lottery_type": "fixed",  # 모든 행 동일 로또
        "lottery_id_name": "Austria Lotto 6/45",
        "columns": {
            "date": "Datum",
            "numbers": ["Zahl 1", "Zahl 2", "Zahl 3", "Zahl 4", "Zahl 5", "Zahl 6"],
            "bonus": None,
            "draw_no": None,
        },
    },
    "Saturday_Lotto.csv": {
        "name": "Australia Saturday Lotto",
        "lottery_type": "fixed",
        "lottery_id_name": "Saturday Lotto",
        "columns": {
            "date": "Date",
            "numbers": ["Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6"],
            "bonus": ["Supp 1", "Supp 2"],
            "draw_no": None,
        },
    },
    "Monday_Lotto.csv": {
        "name": "Australia Monday Lotto",
        "lottery_type": "fixed",
        "lottery_id_name": "Monday Lotto",
        "columns": {
            "date": "Date",
            "numbers": ["Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6"],
            "bonus": ["Supp 1", "Supp 2"],
            "draw_no": None,
        },
    },
    "Wednesday_Lotto.csv": {
        "name": "Australia Wednesday Lotto",
        "lottery_type": "fixed",
        "lottery_id_name": "Wednesday Lotto",
        "columns": {
            "date": "Date",
            "numbers": ["Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6"],
            "bonus": ["Supp 1", "Supp 2"],
            "draw_no": None,
        },
    },
    "Netherlands_Lotto.csv": {
        "name": "Netherlands Lotto",
        "lottery_type": "fixed",
        "lottery_id_name": "Netherlands Lotto",
        "columns": {
            "date": "Trekking",
            "numbers": ["1e balpositie", "2e balpositie", "3e balpositie", "4e balpositie", "5e balpositie", "6e balpositie"],
            "bonus": "Bonusbal",
            "draw_no": None,
        },
    },
    "Belgium_Lotto.csv": {
        "name": "Belgium Lotto",
        "lottery_type": "fixed",
        "lottery_id_name": "Belgium Lotto",
        "columns": {
            "date": "Tirage",
            "numbers": ["Numero 1", "Numero 2", "Numero 3", "Numero 4", "Numero 5", "Numero 6"],
            "bonus": "Bonus",
            "draw_no": None,
        },
    },
    "Hungary_Hatoslotto.csv": {
        "name": "Hungary Hatoslottó",
        "lottery_type": "fixed",
        "lottery_id_name": "Hatoslottó",
        "columns": {
            "date": "Sorsolás dátuma",
            "numbers": ["1. szám", "2. szám", "3. szám", "4. szám", "5. szám", "6. szám"],
            "bonus": None,
            "draw_no": None,
        },
    },
    "Croatia_Loto.csv": {
        "name": "Croatia Loto 6/45",
        "lottery_type": "fixed",
        "lottery_id_name": "Loto 6/45",
        "columns": {
            "date": "Datum izvlačenja",
            "numbers": ["Broj 1", "Broj 2", "Broj 3", "Broj 4", "Broj 5", "Broj 6"],
            "bonus": "Bonus broj",
            "draw_no": None,
        },
    },
}

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

    # draw_date를 문자열로 변환 (date 객체인 경우)
    draw_date_str = draw_date.isoformat() if hasattr(draw_date, 'isoformat') else str(draw_date)

    return {
        "lottery_id": lottery_id,
        "draw_date":  draw_date_str,
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

def parse_csv_line(line, columns):
    """CSV 행을 파싱하여 번호 및 메타데이터 추출"""
    try:
        # 날짜
        date_str = line.get(columns["date"], "").strip()
        if not date_str:
            return None

        # 날짜 포맷 정규화
        try:
            draw_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            try:
                draw_date = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                try:
                    draw_date = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
                except ValueError:
                    return None

        # 번호 (6개)
        nums = []
        for col in columns["numbers"]:
            val = line.get(col, "").strip()
            if val:
                nums.append(int(val))

        if len(nums) != 6:
            return None

        # 보너스 번호
        b1, b2 = None, None
        if columns["bonus"]:
            if isinstance(columns["bonus"], list):
                # 보너스 2개
                if len(columns["bonus"]) >= 1:
                    val = line.get(columns["bonus"][0], "").strip()
                    b1 = int(val) if val else None
                if len(columns["bonus"]) >= 2:
                    val = line.get(columns["bonus"][1], "").strip()
                    b2 = int(val) if val else None
            else:
                # 보너스 1개
                val = line.get(columns["bonus"], "").strip()
                b1 = int(val) if val else None

        # 회차
        draw_no = None
        if columns["draw_no"]:
            val = line.get(columns["draw_no"], "").strip()
            draw_no = int(val) if val and val.isdigit() else None

        return {
            "date": draw_date,
            "nums": sorted(nums),
            "b1": b1,
            "b2": b2,
            "draw_no": draw_no,
        }
    except Exception as e:
        print(f"    [WARN] 파싱 오류: {str(e)}")
        return None

# ─────────────── 메인 ───────────────
def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # lotteries 조회 → name→id 맵
    res = client.table("lotteries").select("id,name").execute()
    name_to_id = {r["name"]: r["id"] for r in res.data}
    print("로또 목록:", list(name_to_id.keys()))
    print()

    base_dir = os.path.dirname(os.path.abspath(__file__))

    for csv_file, config in LOTTERY_CONFIGS.items():
        path = os.path.join(base_dir, csv_file)
        if not os.path.exists(path):
            print(f"[SKIP] 파일 없음: {path}")
            continue

        print(f"\n[{csv_file}] 파싱 시작...")
        rows = []

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for line_idx, line in enumerate(reader, 1):
                parsed = parse_csv_line(line, config["columns"])
                if not parsed:
                    continue

                draw_date = parsed["date"]
                nums = parsed["nums"]
                b1, b2 = parsed["b1"], parsed["b2"]
                draw_no = parsed["draw_no"]

                # 로또별 처리
                if config["lottery_type"] == "dow_based":
                    # 요일별 분류
                    dow = draw_date.weekday()  # 0=월
                    dow_mapping = config.get("dow_mapping", {})
                    lottery_name = dow_mapping.get(dow)

                    if not lottery_name:
                        continue

                    lottery_id = name_to_id.get(lottery_name)
                    if not lottery_id:
                        print(f"  [WARN] DB에 없는 로또명: {lottery_name}")
                        continue

                    rows.append(build_row(lottery_id, draw_date, nums, draw_no, b1, b2))

                elif config["lottery_type"] == "fixed":
                    # 고정 로또
                    lottery_name = config["lottery_id_name"]
                    lottery_id = name_to_id.get(lottery_name)

                    if not lottery_id:
                        print(f"  [WARN] DB에 없는 로또명: {lottery_name}")
                        continue

                    rows.append(build_row(lottery_id, draw_date, nums, draw_no, b1, b2))

        # 업서트 (충돌 무시)
        if rows:
            print(f"  {len(rows)}건 삽입 중...")
            CHUNK = 500
            for i in range(0, len(rows), CHUNK):
                chunk = rows[i:i+CHUNK]
                try:
                    # UPSERT 시도
                    client.table("draws").upsert(
                        chunk, on_conflict="lottery_id,draw_date"
                    ).execute()
                except Exception as e:
                    # UPSERT 실패시 INSERT만 시도 (중복 무시)
                    if "unique" in str(e).lower() or "conflict" in str(e).lower():
                        print(f"    [중복 무시] UPSERT 실패: {str(e)[:80]}")
                        # 개별 INSERT 시도 (중복은 무시)
                        for row in chunk:
                            try:
                                client.table("draws").insert(row).execute()
                            except:
                                pass  # 중복된 행은 무시
                    else:
                        raise
                print(f"    [{i+len(chunk)}/{len(rows)}] 완료")
            print(f"  삽입 완료!")
        else:
            print(f"  데이터 없음 — 건너뜀")

    print("\n전체 완료.")

if __name__ == "__main__":
    main()
