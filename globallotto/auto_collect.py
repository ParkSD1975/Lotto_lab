"""
해외 로또 자동 수집 스크립트
Usage: python -X utf8 auto_collect.py
       (GitHub Actions에서 매주 자동 실행)

각 로또별 Supabase 최신 날짜를 확인하고,
그 이후 신규 추첨 결과만 수집하여 upsert.
"""

import os, re, csv, io, time, random, requests
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

# ─────────────── lotteryextreme displayball 파싱 ───────────────

def parse_displayball(html: str):
    """반환: (main_nums, bonus_nums) or ([], [])"""
    ul_match = re.search(
        r"<ul[^>]*class=['\"]displayball['\"][^>]*>(.*?)</ul>",
        html, re.DOTALL | re.IGNORECASE
    )
    if not ul_match:
        return [], []
    ul_html = ul_match.group(1)
    parts = re.split(r'<li[^>]*class=["\'][^"\']*dbx[^"\']*["\'][^>]*>', ul_html, maxsplit=1)
    main_nums = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', parts[0])]
    bonus_nums = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', parts[1])] if len(parts)>1 else []
    return main_nums, bonus_nums

def fetch_lotteryextreme_date(slug: str, draw_date: date) -> dict | None:
    """lotteryextreme.com/{slug}/lotto-results_details({date}) 파싱"""
    url = f"https://www.lotteryextreme.com/{slug}/lotto-results_details({draw_date.isoformat()})"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"    [ERR] {draw_date}: {e}")
        return None
    if r.status_code != 200:
        return None
    main_nums, bonus_nums = parse_displayball(r.text)
    if len(main_nums) < 6:
        return None
    d = {"draw_date": draw_date.isoformat(),
         "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
         "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5]}
    if bonus_nums:
        d["b1"] = bonus_nums[0]
    return d

# ─────────────── 수집 함수: Austria ───────────────

def collect_austria(lottery_id: str, last_date: date | None) -> int:
    # Wed=2, Sun=6
    dates = generate_draw_dates(last_date, [2, 6])
    print(f"  Austria: {len(dates)}개 날짜 수집 예정")
    draws = []
    for i, d in enumerate(dates):
        row = fetch_lotteryextreme_date("austria", d)
        if row:
            draws.append(row)
        if i < len(dates)-1:
            time.sleep(random.uniform(0.8, 1.5))
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Belgium ───────────────

def collect_belgium(lottery_id: str, last_date: date | None) -> int:
    # Wed=2, Sat=5
    dates = generate_draw_dates(last_date, [2, 5])
    print(f"  Belgium: {len(dates)}개 날짜 수집 예정")
    draws = []
    for i, d in enumerate(dates):
        row = fetch_lotteryextreme_date("belgium", d)
        if row:
            draws.append(row)
        if i < len(dates)-1:
            time.sleep(random.uniform(0.8, 1.5))
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Australia ───────────────

def parse_au_date(txt: str) -> date | None:
    txt = txt.strip()
    parts = re.split(r"[\s,]+", txt)
    day_n = month_n = year_n = None
    for p in parts:
        p_c = re.sub(r"(st|nd|rd|th)$", "", p.lower())
        if p_c in MONTH_MAP:
            month_n = MONTH_MAP[p_c]
        elif p_c.isdigit():
            n = int(p_c)
            if n > 1900:
                year_n = n
            elif 1 <= n <= 31 and day_n is None:
                day_n = n
    if day_n and month_n and year_n:
        try:
            return date(year_n, month_n, day_n)
        except ValueError:
            pass
    return None

def scrape_au_year(slug: str, year: int, filter_weekday: int | None = None) -> list[dict]:
    url = f"https://au.lottonumbers.com/{slug}/results/{year}-archive"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except Exception as e:
        return []
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    for tr in soup.select("tr.winnerRow"):
        date_td = tr.select_one("td.date-row")
        if not date_td:
            continue
        date_text = ""
        for content in date_td.children:
            if getattr(content, "name", None) == "br":
                for s in list(date_td.children)[list(date_td.children).index(content)+1:]:
                    t = str(s).strip()
                    if t:
                        date_text += t
                break
        draw_date = parse_au_date(date_text)
        if not draw_date:
            continue
        if filter_weekday is not None and draw_date.weekday() != filter_weekday:
            continue

        main_ul = tr.select_one("ul.balls[style*='margin-right']")
        if not main_ul:
            continue
        main_nums = [int(li.get_text(strip=True))
                     for li in main_ul.find_all("li")
                     if li.get_text(strip=True).isdigit()]
        supp_lis = tr.select("li.supplementary")
        supps = [int(li.get_text(strip=True)) for li in supp_lis
                 if li.get_text(strip=True).isdigit()]
        if len(main_nums) < 6:
            continue
        rows.append({
            "draw_date": draw_date.isoformat(),
            "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
            "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5],
            "b1": supps[0] if supps else None,
            "b2": supps[1] if len(supps)>1 else None,
        })
    return rows

def collect_australia(lottery_id: str, last_date: date | None,
                      slug: str, filter_weekday: int | None = None) -> int:
    """올해(+작년까지) 페이지만 파싱해 last_date 이후 데이터 upsert"""
    years = [TODAY.year]
    if last_date and last_date.year < TODAY.year:
        years = list(range(last_date.year, TODAY.year+1))
    years = years[-2:]  # 최근 2년만 (효율)

    draws = []
    for year in years:
        rows = scrape_au_year(slug, year, filter_weekday)
        for row in rows:
            if last_date and date.fromisoformat(row["draw_date"]) <= last_date:
                continue
            draws.append(row)
        time.sleep(random.uniform(0.8, 1.3))

    print(f"  Australia {slug}: {len(draws)}건 신규")
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Hungary ───────────────

def collect_hungary(lottery_id: str, last_date: date | None) -> int:
    r = requests.get("https://bet.szerencsejatek.hu/cmsfiles/hatos.csv",
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")

    draws = []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    for row in reader:
        if len(row) < 20:
            continue
        date_str = row[3].strip().rstrip(".")
        parts = date_str.split(".")
        if len(parts) != 3:
            continue
        try:
            draw_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            continue
        if last_date and draw_date <= last_date:
            continue
        if draw_date >= TODAY:
            continue
        try:
            nums = [int(row[14]),int(row[15]),int(row[16]),
                    int(row[17]),int(row[18]),int(row[19])]
        except (ValueError, IndexError):
            continue
        draws.append({
            "draw_date": draw_date.isoformat(),
            "n1":nums[0],"n2":nums[1],"n3":nums[2],
            "n4":nums[3],"n5":nums[4],"n6":nums[5],
        })

    print(f"  Hungary: {len(draws)}건 신규")
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Netherlands ───────────────

def collect_netherlands(lottery_id: str, last_date: date | None) -> int:
    r = requests.get("https://www.lotteryextreme.com/netherlands/lotto-results",
                     headers=HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"  Netherlands: HTTP {r.status_code}")
        return 0

    soup = BeautifulSoup(r.text, "lxml")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return 0

    draws = []
    current_date_str = None
    for tr in tables[1].find_all("tr"):
        text = tr.get_text(separator="|", strip=True)
        if re.match(r"^\d{2}-\d{2}-\d{4}$", text.strip()):
            m = re.match(r"(\d{2})-(\d{2})-(\d{4})", text.strip())
            current_date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        elif current_date_str and text.startswith("Lotto|") and not text.startswith("Lotto XL"):
            d = date.fromisoformat(current_date_str)
            if last_date and d <= last_date:
                current_date_str = None
                continue
            parts = text.split("|")
            nums = [int(p) for p in parts[1:] if p.isdigit()]
            if len(nums) >= 6:
                draws.append({
                    "draw_date": current_date_str,
                    "n1":nums[0],"n2":nums[1],"n3":nums[2],
                    "n4":nums[3],"n5":nums[4],"n6":nums[5],
                    "b1": nums[6] if len(nums)>6 else None,
                })
            current_date_str = None

    # lotteryguru page 1 보완
    try:
        r2 = requests.get(
            "https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page=1",
            headers=HEADERS, timeout=15)
        if r2.status_code == 200:
            soup2 = BeautifulSoup(r2.text, "lxml")
            for block in soup2.select("div.lg-line"):
                date_div = block.select_one("div.lg-date.has-text-right")
                if not date_div:
                    continue
                try:
                    txt = date_div.get_text(separator=" ", strip=True).split()
                    draw_date = date(int(txt[2]), MONTH_MAP[txt[1].lower()[:3]], int(txt[0]))
                except:
                    continue
                if last_date and draw_date <= last_date:
                    continue
                lis = block.select("li.lg-number")
                main_nums, bonus = [], None
                for li in lis:
                    n_txt = li.get_text(strip=True)
                    if not n_txt.isdigit():
                        continue
                    n = int(n_txt)
                    if "lg-reversed" in li.get("class", []):
                        bonus = n
                    else:
                        main_nums.append(n)
                if len(main_nums) < 6:
                    continue
                row = {"draw_date": draw_date.isoformat(),
                       "n1":main_nums[0],"n2":main_nums[1],"n3":main_nums[2],
                       "n4":main_nums[3],"n5":main_nums[4],"n6":main_nums[5],
                       "b1": bonus}
                # 중복 제거
                if not any(x["draw_date"] == row["draw_date"] for x in draws):
                    draws.append(row)
    except Exception as e:
        print(f"  Netherlands guru fallback err: {e}")

    print(f"  Netherlands: {len(draws)}건 신규")
    return upsert_draws(lottery_id, draws)

# ─────────────── 수집 함수: Croatia ───────────────

def collect_croatia(lottery_id: str, last_date: date | None) -> int:
    draws = []
    for page in range(1, 4):  # 최신 2~3 페이지만
        url = (f"https://lotteryguru.com/croatia-lottery-results"
               f"/hr-loto-6/hr-loto-6-results-history?page={page}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
        except Exception:
            break
        if r.status_code != 200:
            break

        soup = BeautifulSoup(r.text, "lxml")
        if "Page not found" in soup.get_text():
            break

        page_new = 0
        stop_page = False
        for block in soup.select("div.lg-line"):
            date_div = block.select_one("div.lg-date.has-text-right")
            if not date_div:
                continue
            try:
                txt = date_div.get_text(separator=" ", strip=True).split()
                draw_date = date(int(txt[2]), MONTH_MAP[txt[1].lower()[:3]], int(txt[0]))
            except:
                continue
            if last_date and draw_date <= last_date:
                stop_page = True
                break

            lis = block.select("li.lg-number")
            main_nums, bonus = [], None
            for li in lis:
                n_txt = li.get_text(strip=True)
                if not n_txt.isdigit():
                    continue
                n = int(n_txt)
                if "lg-reversed" in li.get("class", []):
                    bonus = n
                else:
                    main_nums.append(n)
            if len(main_nums) < 6:
                continue
            draws.append({"draw_date": draw_date.isoformat(),
                          "n1":main_nums[0],"n2":main_nums[1],"n3":main_nums[2],
                          "n4":main_nums[3],"n5":main_nums[4],"n6":main_nums[5],
                          "b1": bonus})
            page_new += 1

        if stop_page or page_new == 0:
            break
        time.sleep(random.uniform(0.8, 1.3))

    print(f"  Croatia: {len(draws)}건 신규")
    return upsert_draws(lottery_id, draws)

# ─────────────── 메인 ───────────────

def run_collector(name: str, fn):
    print(f"\n{'─'*40}")
    print(f"[{name}] 수집 시작")
    try:
        lottery_id = get_lottery_id(name)
        last_date  = get_latest_date(lottery_id)
        print(f"  최신 날짜: {last_date}")
        inserted = fn(lottery_id, last_date)
        print(f"  ✓ {inserted}건 upsert")
        return inserted
    except Exception as e:
        print(f"  [ERR] {e}")
        return 0

def main():
    print(f"=== 자동 수집 시작: {TODAY} ===\n")
    total = 0

    total += run_collector("Austria Lotto 6/45",
        lambda lid, ld: collect_austria(lid, ld))

    total += run_collector("Belgium Lotto",
        lambda lid, ld: collect_belgium(lid, ld))

    total += run_collector("Saturday Lotto",
        lambda lid, ld: collect_australia(lid, ld, "saturday-lotto", filter_weekday=5))

    total += run_collector("Monday Lotto",
        lambda lid, ld: collect_australia(lid, ld, "weekday-windfall", filter_weekday=0))

    total += run_collector("Wednesday Lotto",
        lambda lid, ld: collect_australia(lid, ld, "weekday-windfall", filter_weekday=2))

    total += run_collector("Hatoslottó",
        lambda lid, ld: collect_hungary(lid, ld))

    total += run_collector("Netherlands Lotto",
        lambda lid, ld: collect_netherlands(lid, ld))

    total += run_collector("Loto 6/45",
        lambda lid, ld: collect_croatia(lid, ld))

    print(f"\n{'='*40}")
    print(f"=== 완료: 총 {total}건 업데이트 ({TODAY}) ===")

if __name__ == "__main__":
    main()
