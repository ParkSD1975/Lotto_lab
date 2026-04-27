"""lotteryguru Netherlands 파서 디버그"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}
r = requests.get(
    "https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page=1",
    headers=HEADERS, timeout=15
)
soup = BeautifulSoup(r.text, "lxml")

# lg-line 직접 탐색
lg_lines = soup.select("div.lg-line")
print(f"div.lg-line: {len(lg_lines)}개")

if lg_lines:
    block = lg_lines[0]
    print("첫 번째 lg-line HTML:")
    print(block.prettify()[:1500])
