"""lotteryextreme.com Netherlands 페이지 탐색"""
import requests, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

# 1. 메인 Netherlands 페이지
urls_to_try = [
    "https://www.lotteryextreme.com/netherlands",
    "https://www.lotteryextreme.com/netherlands/lotto",
    "https://www.lotteryextreme.com/netherlands/nederlandse-lotto-results_details(2024-01-06)",
    "https://www.lotteryextreme.com/netherlands/lotto6-results_details(2024-01-06)",
    "https://www.lotteryextreme.com/netherlands/lotto-6-45-results_details(2024-01-06)",
    "https://www.lotteryextreme.com/croatia/loto645-results_details(2024-01-10)",
    "https://www.lotteryextreme.com/croatia/loto-6-45-results_details(2024-01-10)",
]

for url in urls_to_try:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"HTTP {r.status_code}  {url}")
        if r.status_code == 200:
            # 링크 찾기
            links = re.findall(r'href=["\']([^"\']*lotteryextreme[^"\']*)["\']', r.text)
            if links:
                print(f"  Found links: {links[:5]}")
            else:
                print(f"  Content preview: {r.text[500:1000]}")
    except Exception as e:
        print(f"ERR {url}: {e}")
