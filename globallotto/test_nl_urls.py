"""Netherlands/Croatia 추가 URL 패턴 탐색"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

tests = [
    # lotteryextreme - 다른 패턴
    ("LE NL cold",    "https://www.lotteryextreme.com/netherlands/lotto-cold-numbers"),
    ("LE NL past",    "https://www.lotteryextreme.com/netherlands/lotto-past_winning_numbers"),
    ("LE NL history", "https://www.lotteryextreme.com/netherlands/lotto-winning_numbers_history"),
    # lotteryguru pages
    ("guru NL p1",    "https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page=1"),
    ("guru NL p7",    "https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history?page=7"),
    # lottolyzer
    ("lyzer NL",      "https://www.lottolyzer.com/app/lotteries/netherlands-lotto/draws"),
]

for name, url in tests:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        print(f"\n{name}: HTTP {r.status_code}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            # 날짜/번호 탐색
            dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{2}[-/]\d{2}[-/]\d{4}', text)
            nums6 = re.findall(r'\b([1-9]|[1-3]\d|4[0-5])\b', text)
            print(f"  날짜: {dates[:5]}")
            print(f"  텍스트: {text[:400]}")
    except Exception as e:
        print(f"\n{name}: ERR - {e}")
