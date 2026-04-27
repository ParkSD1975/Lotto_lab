"""lotteryextreme Netherlands 데이터 테이블 (Table 1) 구조 분석"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}
r = requests.get("https://www.lotteryextreme.com/netherlands/lotto-results", headers=HEADERS, timeout=15)
soup = BeautifulSoup(r.text, "lxml")

tables = soup.find_all("table")
main_table = tables[1]  # 120 rows
rows = main_table.find_all("tr")

print(f"Table 1: {len(rows)} rows")
# 실제 데이터가 있는 row 탐색
for i, row in enumerate(rows):
    text = row.get_text(separator="|", strip=True)
    # displayball이 있거나 날짜처럼 보이는 row
    if row.find("ul", class_="displayball") or re.search(r'\d{1,2}/\d{1,2}/\d{4}|\w+day', text, re.I):
        print(f"  row {i}: {repr(text[:200])}")
        # 이전 row도 출력
        if i > 0:
            prev_text = rows[i-1].get_text(separator="|", strip=True)
            print(f"    prev row {i-1}: {repr(prev_text[:150])}")
        if i < len(rows)-1:
            next_text = rows[i+1].get_text(separator="|", strip=True)
            print(f"    next row {i+1}: {repr(next_text[:150])}")
        print()
        if i > 30:
            break
