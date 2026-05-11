import os, sys, requests
from datetime import date
from bs4 import BeautifulSoup

MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def test_guru(country_path, slug):
    url = f"https://lotteryguru.com/{country_path}/{slug}/{slug}-results-history?page=1"
    print(f"Testing URL: {url}")
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"Failed with status: {r.status_code}")
        return
    
    soup = BeautifulSoup(r.text, "lxml")
    blocks = soup.select("div.lg-line")
    print(f"Found {len(blocks)} blocks")
    
    for block in blocks[:3]:
        date_div = block.select_one("div.lg-date")
        if not date_div: continue
        raw_date_text = date_div.get_text(separator=" ", strip=True)
        print(f"  Raw Date: {raw_date_text}")
        
        # Numbers
        lis = block.select("li.lg-number")
        main_nums = []
        bonus = None
        for li in lis:
            val_txt = li.get_text(strip=True)
            if not val_txt.isdigit(): continue
            n = int(val_txt)
            if "lg-reversed" in li.get("class", []):
                bonus = n
            else:
                main_nums.append(n)
        print(f"    Numbers: {main_nums} (Bonus: {bonus})")

print("--- Austria ---")
test_guru("austria-lottery-results", "at-lotto")
print("\n--- Australia Sat ---")
test_guru("australia-lottery-results", "au-saturday-lotto")
