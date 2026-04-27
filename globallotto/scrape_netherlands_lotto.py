"""
Netherlands Lotto 데이터 수집
Source 1: lotteryextreme.com/netherlands/lotto-results  (최근 ~13회)
Source 2: lotteryguru.com  (7페이지, ~2025-02 이후 ~70-80회)

lotteryguru 구조:
  div.lg-line
    div.lg-date.has-text-right: "<strong>18 Apr</strong> 2026"
    ul.lg-numbers-small
      li.lg-number : 메인 번호
      li.lg-number.lg-reversed : 보너스
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
    """<div class='lg-date has-text-right'> → '2026-04-18'"""
    try:
        text = div.get_text(separator=" ", strip=True)  # "18 Apr 2026"
        parts = text.split()
        day = int(parts[0])
        month = MONTH_MAP.get(parts[1].lower()[:3])
        year = int(parts[2])
        return date(year, month, day).isoformat()
    except:
        return None

def parse_date_dmy(s: str) -> str | None:
    """'18-04-2026' → '2026-04-18'"""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", s.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


# ── Source 1: lotteryextreme ──
def scrape_lotteryextreme() -> dict:
    rows = {}
    r = requests.get("https://www.lotteryextreme.com/netherlands/lotto-results",
                     headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return rows

    soup = BeautifulSoup(r.text, "lxml")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return rows

    trs = tables[1].find_all("tr")
    current_date = None
    for tr in trs:
        text = tr.get_text(separator="|", strip=True)
        if re.match(r"^\d{2}-\d{2}-\d{4}$", text.strip()):
            current_date = parse_date_dmy(text.strip())
        elif current_date and text.startswith("Lotto|") and not text.startswith("Lotto XL"):
            parts = text.split("|")
            nums = [int(p) for p in parts[1:] if p.isdigit()]
            if len(nums) >= 6:
                bonus = nums[6] if len(nums) >= 7 else None
                rows[current_date] = {
                    "date": current_date,
                    "n1": nums[0], "n2": nums[1], "n3": nums[2],
                    "n4": nums[3], "n5": nums[4], "n6": nums[5],
                    "bonus": bonus or ""
                }
                current_date = None

    print(f"  lotteryextreme: {len(rows)}건")
    return rows


# ── Source 2: lotteryguru ──
def scrape_lotteryguru() -> dict:
    rows = {}
    for page in range(1, 8):
        url = f"https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page={page}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            break

        soup = BeautifulSoup(r.text, "lxml")
        blocks = soup.select("div.lg-line")
        page_draws = 0

        for block in blocks:
            # 날짜
            date_div = block.select_one("div.lg-date.has-text-right")
            if not date_div:
                continue
            draw_date = parse_guru_date(date_div)
            if not draw_date:
                continue

            # 번호
            lis = block.select("li.lg-number")
            main_nums = []
            bonus = None
            for li in lis:
                val_txt = li.get_text(strip=True)
                if not val_txt.isdigit():
                    continue
                n = int(val_txt)
                if "lg-reversed" in li.get("class", []):
                    bonus = n
                else:
                    main_nums.append(n)

            if len(main_nums) < 6:
                continue

            rows[draw_date] = {
                "date": draw_date,
                "n1": main_nums[0], "n2": main_nums[1], "n3": main_nums[2],
                "n4": main_nums[3], "n5": main_nums[4], "n6": main_nums[5],
                "bonus": bonus or ""
            }
            page_draws += 1

        print(f"  lotteryguru page {page}: {page_draws}건")
        time.sleep(random.uniform(0.8, 1.3))

    return rows


def main():
    all_draws = {}

    print("=== lotteryextreme ===")
    all_draws.update(scrape_lotteryextreme())

    print("\n=== lotteryguru (7 pages) ===")
    all_draws.update(scrape_lotteryguru())

    sorted_rows = sorted(all_draws.values(), key=lambda r: r["date"])

    out = os.path.join(BASE_DIR, "Netherlands_Lotto_real.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date","n1","n2","n3","n4","n5","n6","bonus"])
        writer.writeheader()
        writer.writerows(sorted_rows)

    print(f"\n✓ Netherlands Lotto 총 {len(sorted_rows)}건 → {out}")
    if sorted_rows:
        print(f"  기간: {sorted_rows[0]['date']} ~ {sorted_rows[-1]['date']}")

if __name__ == "__main__":
    main()
