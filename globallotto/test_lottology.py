"""lottology.com / lotteryguru.com 데이터 탐색"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

urls = [
    ("lottology NL",  "https://www.lottology.com/europe/nl_lotto/past-draws-archive/"),
    ("lottology HR",  "https://www.lottology.com/europe/hr_loto/past-draws-archive/"),
    ("lotteryguru NL","https://lotteryguru.com/netherlands-lottery-results/nl-lotto/nl-lotto-results-history"),
    ("lotteryguru HR","https://lotteryguru.com/croatia-lottery-results/hr-loto/hr-loto-results-history"),
    ("lotto.nl",      "https://lotto.nederlandseloterij.nl/trekkingsuitslag"),
]

for name, url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"\n{name}: HTTP {r.status_code}  {url}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            # 날짜, 번호 관련 텍스트 찾기
            text = soup.get_text()[:2000]
            # 숫자 패턴 찾기
            dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}\.\d{2}\.\d{4}', text)
            if dates:
                print(f"  날짜 발견: {dates[:5]}")
            print(f"  텍스트 일부: {text[200:600]}")
    except Exception as e:
        print(f"\n{name}: ERR - {e}")
