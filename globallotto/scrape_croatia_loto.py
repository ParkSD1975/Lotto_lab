"""
Croatia Loto 6/45 데이터 수집
Source: lotteryguru.com/croatia-lottery-results/hr-loto-6/hr-loto-6-results-history?page=N
        (Netherlands와 동일한 div.lg-line 구조)
"""

import os, csv, time, random, re, requests
from datetime import date
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"}

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

def parse_guru_date(div) -> str | None:
    try:
        text = div.get_text(separator=" ", strip=True)
        parts = text.split()
        day = int(parts[0])
        month = MONTH_MAP.get(parts[1].lower()[:3])
        year = int(parts[2])
        return date(year, month, day).isoformat()
    except:
        return None

def scrape_page(page: int) -> list[dict]:
    url = (f"https://lotteryguru.com/croatia-lottery-results"
           f"/hr-loto-6/hr-loto-6-results-history?page={page}")
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"  page {page}: HTTP {r.status_code}")
        return []

    soup = BeautifulSoup(r.text, "lxml")

    # 페이지 없음 확인
    if "Page not found" in soup.get_text() or "not found" in soup.title.string.lower() if soup.title else False:
        return []

    draws = []
    for block in soup.select("div.lg-line"):
        date_div = block.select_one("div.lg-date.has-text-right")
        if not date_div:
            continue
        draw_date = parse_guru_date(date_div)
        if not draw_date:
            continue

        lis = block.select("li.lg-number")
        main_nums, bonus = [], None
        for li in lis:
            txt = li.get_text(strip=True)
            if not txt.isdigit():
                continue
            n = int(txt)
            if "lg-reversed" in li.get("class", []):
                bonus = n
            else:
                main_nums.append(n)

        if len(main_nums) < 6:
            continue

        draws.append({
            "date": draw_date,
            "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
            "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5],
            "bonus": bonus or ""
        })
    return draws


def main():
    all_rows = {}
    page = 1
    while True:
        rows = scrape_page(page)
        if not rows:
            print(f"  page {page}: 0건 → 종료")
            break
        for r in rows:
            all_rows[r["date"]] = r
        print(f"  page {page}: {len(rows)}건 (누적 {len(all_rows)})")
        page += 1
        time.sleep(random.uniform(0.8, 1.3))
        if page > 30:  # 안전장치
            break

    sorted_rows = sorted(all_rows.values(), key=lambda r: r["date"])
    out = os.path.join(BASE_DIR, "Croatia_Loto_real.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date","n1","n2","n3","n4","n5","n6","bonus"])
        writer.writeheader()
        writer.writerows(sorted_rows)

    print(f"\n✓ Croatia Loto 6 총 {len(sorted_rows)}건 → {out}")
    if sorted_rows:
        print(f"  기간: {sorted_rows[0]['date']} ~ {sorted_rows[-1]['date']}")

if __name__ == "__main__":
    main()
