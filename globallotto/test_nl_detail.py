"""Netherlands lotteryextreme 최신 날짜 + 링크 탐색"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

# 1. 최신 날짜로 results_details 시도
for date_str in ["2026-04-18", "2025-06-07", "2024-06-08"]:
    url = f"https://www.lotteryextreme.com/netherlands/lotto-results_details({date_str})"
    r = requests.get(url, headers=HEADERS, timeout=10)
    print(f"HTTP {r.status_code}: {url}")

# 2. cold-numbers 페이지에서 링크 탐색
print("\n=== cold-numbers 링크 ===")
r2 = requests.get("https://www.lotteryextreme.com/netherlands/lotto-cold-numbers", headers=HEADERS, timeout=10)
soup = BeautifulSoup(r2.text, "lxml")
# 모든 internal 링크
links = set()
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "netherlands" in href.lower() or "lotto" in href.lower():
        links.add(href)
for l in sorted(links)[:30]:
    print(f"  {l}")

# 3. lotteryguru 첫 페이지 HTML 구조 확인
print("\n=== lotteryguru 구조 ===")
r3 = requests.get(
    "https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page=1",
    headers=HEADERS, timeout=12
)
soup3 = BeautifulSoup(r3.text, "lxml")
# History 섹션 찾기
history_div = soup3.find("div", class_=re.compile("history|result", re.I))
if history_div:
    print(repr(str(history_div)[:1000]))
else:
    # 다른 방법으로 번호 탐색
    rows = soup3.select("div.draw-row, tr.result, div.result-row, div.past-result")
    print(f"  result rows: {len(rows)}")
    # 일반적인 테이블 찾기
    tables = soup3.find_all("table")
    print(f"  tables: {len(tables)}")
    # 날짜-번호 패턴 탐색
    text = soup3.get_text(separator="\n")
    # 4월 18 형식 탐색
    date_blocks = re.findall(r'(?:Saturday|Sunday|Monday|Wednesday|Friday)\s+\d+\s+\w+\s+\d{4}(?:\s+\d+)+', text)
    for db in date_blocks[:5]:
        print(f"  Block: {repr(db)}")
