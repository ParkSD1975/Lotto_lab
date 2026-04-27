"""Croatia LOTO 6 링크 탐색"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

# Croatia 메인 결과 페이지에서 LOTO 6 링크 찾기
r = requests.get("https://lotteryguru.com/croatia-lottery-results", headers=HEADERS, timeout=15)
soup = BeautifulSoup(r.text, "lxml")

# 모든 링크 출력
links = soup.find_all("a", href=True)
for a in links:
    href = a["href"]
    text = a.get_text(strip=True)
    if "croatia" in href.lower() or "loto" in text.lower() or "lotto" in text.lower():
        print(f"{text!r:30} → {href}")
