"""
해외 로또 자동 수집 스크립트
Usage: python -X utf8 auto_collect.py
       (GitHub Actions에서 매주 자동 실행)

각 로또별 Supabase 최신 날짜를 확인하고,
그 이후 신규 추첨 결과만 수집하여 upsert.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os, re, csv, time, random, requests
from datetime import date, timedelta
from bs4 import BeautifulSoup
from supabase import create_client

# ─────────────── Supabase 설정 ───────────────
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://dkcflmyoscudawleglzb.supabase.co"
)
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo"
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TODAY = date.today()
BATCH_SIZE = 100

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

# ─────────────── 공통 유틸 ───────────────

def calc_stats(nums: list[int]) -> dict:
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

def get_lottery_id(name: str) -> str:
    res = supabase.table("lotteries").select("id").eq("name", name).single().execute()
    return res.data["id"]

def get_latest_date(lottery_id: str) -> date | None:
    res = supabase.table("draws") \
        .select("draw_date") \
        .eq("lottery_id", lottery_id) \
        .order("draw_date", desc=True) \
        .limit(1).execute()
    if res.data:
        return date.fromisoformat(res.data[0]["draw_date"])
    return None

def upsert_draws(lottery_id: str, draws: list[dict]) -> int:
    """draws: [{ draw_date, n1..n6, b1(opt), b2(opt), stats... }]"""
    if not draws:
        return 0
    records = []
    for d in draws:
        nums = [d[f"n{i}"] for i in range(1,7)]
        rec = {
            "lottery_id": lottery_id,
            "draw_date": d["draw_date"],
            "n1": d["n1"], "n2": d["n2"], "n3": d["n3"],
            "n4": d["n4"], "n5": d["n5"], "n6": d["n6"],
            "b1": d.get("b1"), "b2": d.get("b2"),
            **calc_stats(nums),
        }
        records.append(rec)

    inserted = 0
    for i in range(0, len(records), BATCH_SIZE):
        chunk = records[i:i+BATCH_SIZE]
        supabase.table("draws").upsert(chunk, on_conflict="lottery_id,draw_date").execute()
        inserted += len(chunk)
    return inserted

def generate_draw_dates(last_date: date | None, draw_weekdays: list[int]) -> list[date]:
    """last_date 다음 추첨일부터 오늘(미포함)까지의 추첨 날짜 목록"""
    start = (last_date + timedelta(days=1)) if last_date else date(2002, 1, 1)
    result = []
    d = start
    while d < TODAY:
        if d.weekday() in draw_weekdays:
            result.append(d)
        d += timedelta(days=1)
    return result

# ─────────────── 수집 함수: 공통 Guru 파서 (Austria, Australia, Philippines, Croatia 등) ───────────────

def collect_via_guru(lottery_id: str, last_date: date | None, 
                    country_path: str, slug: str, 
                    filter_weekday: int | None = None) -> int:
    """lotteryguru.com 기반 공통 수집 함수"""
    draws = []
    # 보통 최신 데이터는 1~2페이지 내에 있음
    for page in range(1, 3): 
        url = f"https://lotteryguru.com/{country_path}/{slug}/{slug}-results-history?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, "lxml")
            
            blocks = soup.select("div.lg-line")
            if not blocks: break
            
            page_new = 0
            stop_page = False
            for block in blocks:
                # 날짜 파싱 (요일과 날짜가 별도 태그일 수 있으므로 전체 텍스트 사용)
                try:
                    # "Wednesday 29 Apr 2026" 등 전체 텍스트 추출
                    raw_date_text = block.get_text(separator=" ", strip=True)
                    clean_text = raw_date_text.replace(",", " ").strip()
                    parts = clean_text.split()
                    
                    day = month = year = None
                    # 1. 월 찾기 (문자열 부분에서)
                    for p in parts:
                        p_l = p.lower()
                        if p_l[:3] in MONTH_MAP:
                            month = MONTH_MAP[p_l[:3]]
                            break
                    
                    # 2. 숫자(일, 년) 찾기 - 정규식으로 안전하게 추출
                    nums_in_text = re.findall(r'\d+', clean_text)
                    for n_str in nums_in_text:
                        val = int(n_str)
                        if val > 1900: 
                            year = val
                        elif 1 <= val <= 31 and day is None:
                            day = val
                    
                    if not (day and month and year): continue
                    draw_date = date(year, month, day)
                except:
                    continue
                
                if last_date and draw_date <= last_date:
                    stop_page = True
                    break
                if filter_weekday is not None and draw_date.weekday() != filter_weekday:
                    continue
                if draw_date >= TODAY: # 오늘 추첨분은 아직 안나왔을 수 있으므로 안전하게 패스
                    continue

                # 번호 파싱 (ul.lg-numbers-small 또는 ul.lg-numbers)
                lis = block.select("li.lg-number")
                if not lis: continue
                
                main_nums = []
                bonus = None
                for li in lis:
                    val_txt = li.get_text(strip=True)
                    if not val_txt.isdigit(): continue
                    n = int(val_txt)
                    # lg-reversed 클래스가 있으면 보너스 번호
                    if "lg-reversed" in li.get("class", []):
                        bonus = n
                    else:
                        main_nums.append(n)
                
                if len(main_nums) < 6: continue
                
                draws.append({
                    "draw_date": draw_date.isoformat(),
                    "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
                    "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5],
                    "b1": bonus
                })
                page_new += 1
            
            if stop_page or page_new == 0: break
            time.sleep(random.uniform(0.8, 1.5))
            
        except Exception as e:
            print(f"    [ERR] Guru 파싱 중 오류 ({slug}): {e}")
            break
            
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Hungary (CSV 기반 유지) ───────────────

def collect_hungary(lottery_id: str, last_date: date | None, filter_weekday: int | None = None) -> int:
    try:
        r = requests.get("https://bet.szerencsejatek.hu/cmsfiles/hatos.csv",
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig", errors="replace")

        draws = []
        reader = csv.reader(io.StringIO(text), delimiter=";")
        for row in reader:
            if len(row) < 20: continue
            date_str = row[3].strip().rstrip(".")
            parts = date_str.split(".")
            if len(parts) != 3: continue
            try:
                draw_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError: continue
            
            if filter_weekday is not None and draw_date.weekday() != filter_weekday:
                continue
            if last_date and draw_date <= last_date:
                continue
            if draw_date >= TODAY:
                continue
            try:
                nums = [int(row[14]),int(row[15]),int(row[16]),
                        int(row[17]),int(row[18]),int(row[19])]
            except (ValueError, IndexError): continue
            
            draws.append({
                "draw_date": draw_date.isoformat(),
                "n1":nums[0],"n2":nums[1],"n3":nums[2],
                "n4":nums[3],"n5":nums[4],"n6":nums[5],
            })

        print(f"  Hungary: {len(draws)}건 신규")
        return upsert_draws(lottery_id, draws)
    except Exception as e:
        print(f"  [ERR] Hungary CSV 수집 실패: {e}")
        return 0

# ─────────────── 메인 ───────────────

def run_collector(name: str, fn):
    print(f"\n{'─'*40}")
    print(f"[{name}] 수집 시작")
    try:
        lottery_id = get_lottery_id(name)
        last_date  = get_latest_date(lottery_id)
        print(f"  최근 날짜: {last_date}")
        inserted = fn(lottery_id, last_date)
        print(f"  ✓ {inserted}건 upsert")
        return inserted
    except Exception as e:
        print(f"  [ERR] {e}")
        return 0

def main():
    print(f"=== 자동 수집 시작: {TODAY} ===\n")
    total = 0

    # 1. Austria (수요일/일요일 분리)
    total += run_collector("Austria Lotto (수)",
        lambda lid, ld: collect_via_guru(lid, ld, "austria-lottery-results", "at-lotto", filter_weekday=2))
    total += run_collector("Austria Lotto (일)",
        lambda lid, ld: collect_via_guru(lid, ld, "austria-lottery-results", "at-lotto", filter_weekday=6))

    # 2. Belgium (Guru로 변경 - 안정성 확보)
    total += run_collector("Belgium Lotto (수)",
        lambda lid, ld: collect_via_guru(lid, ld, "belgium-lottery-results", "be-lotto", filter_weekday=2))
    total += run_collector("Belgium Lotto (토)",
        lambda lid, ld: collect_via_guru(lid, ld, "belgium-lottery-results", "be-lotto", filter_weekday=5))

    # 3. Australia (Guru로 변경 - 403 차단 우회)
    total += run_collector("Saturday Lotto",
        lambda lid, ld: collect_via_guru(lid, ld, "australia-lottery-results", "au-saturday-lotto", filter_weekday=5))
    total += run_collector("Monday Lotto",
        lambda lid, ld: collect_via_guru(lid, ld, "australia-lottery-results", "au-weekday-windfall", filter_weekday=0))
    total += run_collector("Wednesday Lotto",
        lambda lid, ld: collect_via_guru(lid, ld, "australia-lottery-results", "au-weekday-windfall", filter_weekday=2))

    # 4. Hungary (CSV 유지)
    total += run_collector("Hatoslottó (목)",
        lambda lid, ld: collect_hungary(lid, ld, filter_weekday=3))
    total += run_collector("Hatoslottó (일)",
        lambda lid, ld: collect_hungary(lid, ld, filter_weekday=6))

    # 5. Netherlands (Guru로 통합 및 강화)
    total += run_collector("Netherlands Lotto",
        lambda lid, ld: collect_via_guru(lid, ld, "netherlands-lottery-results", "nl-lotto"))
    total += run_collector("Netherlands Lotto XL",
        lambda lid, ld: collect_via_guru(lid, ld, "netherlands-lottery-results", "nl-lotto-xl"))

    # 6. Croatia (Guru 기반 유지)
    total += run_collector("Loto 6/45 (목)",
        lambda lid, ld: collect_via_guru(lid, ld, "croatia-lottery-results", "hr-loto-6", filter_weekday=3))
    total += run_collector("Loto 6/45 (일)",
        lambda lid, ld: collect_via_guru(lid, ld, "croatia-lottery-results", "hr-loto-6", filter_weekday=6))

    # 7. Philippines (Guru 기반 유지)
    total += run_collector("Mega 645 (월)",
        lambda lid, ld: collect_via_guru(lid, ld, "philippines-lottery-results", "ph-mega-lotto-6-45", filter_weekday=0))
    total += run_collector("Mega 645 (수)",
        lambda lid, ld: collect_via_guru(lid, ld, "philippines-lottery-results", "ph-mega-lotto-6-45", filter_weekday=2))
    total += run_collector("Mega 645 (금)",
        lambda lid, ld: collect_via_guru(lid, ld, "philippines-lottery-results", "ph-mega-lotto-6-45", filter_weekday=4))

    print(f"\n{'='*40}")
    print(f"=== 완료: 총 {total}건 업데이트 ({TODAY}) ===")

if __name__ == "__main__":
    main()
