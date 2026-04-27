"""
Australia Saturday / Monday / Wednesday Lotto 실제 데이터 수집
Sources:
  Saturday  : https://au.lottonumbers.com/saturday-lotto/results/{year}-archive
  Mon+Wed   : https://au.lottonumbers.com/weekday-windfall/results/{year}-archive
              (2006년부터; 월·수 추첨 요일로 구분)

HTML 구조 (실제 확인):
  <tr class="winnerRow">
    <td class="noBefore colour date-row">
      <strong>Draw 4,429</strong><br>Saturday 30 December 2023
    </td>
    <td class="noBefore balls-row">
      <ul class="balls" style="margin-right:5px;">   ← 메인 6개
        <li class="ball ball -b278">2</li>...
      </ul>
      <ul class="balls">                             ← 보충 2개
        <li class="ball supplementary -b278">22</li>...
      </ul>
    </td>
  </tr>
"""

import os, csv, time, random, re
from datetime import date
from bs4 import BeautifulSoup
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12
}

def parse_au_date(txt: str):
    """
    'Saturday 30 December 2023' → date(2023, 12, 30)
    """
    txt = txt.strip()
    # ISO
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", txt)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

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


def scrape_year(lottery_slug: str, year: int):
    """
    au.lottonumbers.com/{slug}/results/{year}-archive 에서 모든 draws 파싱
    반환: list of dict {date, n1..n6, supp1, supp2}
    """
    url = f"https://au.lottonumbers.com/{lottery_slug}/results/{year}-archive"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"  [ERR] {lottery_slug} {year}: {e}")
        return []

    if r.status_code != 200:
        print(f"  [SKIP] {lottery_slug} {year}: HTTP {r.status_code}")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    rows = []

    for tr in soup.select("tr.winnerRow"):
        # 날짜
        date_td = tr.select_one("td.date-row")
        if not date_td:
            continue
        # <strong>Draw N</strong><br>Saturday 30 December 2023
        # br 뒤 텍스트 추출
        date_text = ""
        for content in date_td.children:
            if getattr(content, "name", None) == "br":
                # br 이후의 텍스트 노드
                br_idx = list(date_td.children).index(content)
                siblings = list(date_td.children)
                for s in siblings[br_idx+1:]:
                    t = str(s).strip()
                    if t:
                        date_text += t
                break

        draw_date = parse_au_date(date_text)
        if not draw_date:
            continue

        # 메인 번호: margin-right:5px 속성 있는 ul.balls
        main_ul = tr.select_one("ul.balls[style*='margin-right']")
        if not main_ul:
            continue
        main_nums = [int(li.get_text(strip=True))
                     for li in main_ul.find_all("li")
                     if li.get_text(strip=True).isdigit()]

        # 보충 번호: supplementary 클래스 li
        supp_lis = tr.select("li.supplementary")
        supps = [int(li.get_text(strip=True))
                 for li in supp_lis
                 if li.get_text(strip=True).isdigit()]

        if len(main_nums) < 6:
            continue

        rows.append({
            "date":  draw_date.isoformat(),
            "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
            "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5],
            "supp1": supps[0] if len(supps) > 0 else "",
            "supp2": supps[1] if len(supps) > 1 else "",
        })

    return rows


def main():
    sat_rows = []
    mon_rows = []
    wed_rows = []

    # ── Saturday Lotto (2002 ~ 2026)
    print("=== Saturday Lotto 수집 ===")
    for year in range(2002, 2027):
        rows = scrape_year("saturday-lotto", year)
        sat_rows.extend(rows)
        print(f"  {year}: {len(rows)}건 (누적 {len(sat_rows)})")
        time.sleep(random.uniform(0.8, 1.5))

    # ── Weekday Windfall (Mon/Wed) 2006 ~ 2026
    print("\n=== Weekday Windfall (Mon/Wed) 수집 ===")
    for year in range(2006, 2027):
        rows = scrape_year("weekday-windfall", year)
        for row in rows:
            d = date.fromisoformat(row["date"])
            if d.weekday() == 0:
                mon_rows.append(row)
            elif d.weekday() == 2:
                wed_rows.append(row)
        print(f"  {year}: Mon {sum(1 for r in rows if date.fromisoformat(r['date']).weekday()==0)}건 / "
              f"Wed {sum(1 for r in rows if date.fromisoformat(r['date']).weekday()==2)}건")
        time.sleep(random.uniform(0.8, 1.5))

    # ── CSV 저장
    fieldnames = ["date","n1","n2","n3","n4","n5","n6","supp1","supp2"]

    def save_csv(rows, filename):
        path = os.path.join(BASE_DIR, filename)
        sorted_rows = sorted(rows, key=lambda r: r["date"])
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_rows)
        print(f"✓ {filename}: {len(sorted_rows)}건")
        return path

    print("\n=== CSV 저장 ===")
    save_csv(sat_rows, "Saturday_Lotto_real.csv")
    save_csv(mon_rows, "Monday_Lotto_real.csv")
    save_csv(wed_rows, "Wednesday_Lotto_real.csv")

    print("\n수집 완료. 다음: python -X utf8 import_australia_real.py")

if __name__ == "__main__":
    main()
