"""Wayback Machine 직접 접근 테스트"""
import requests, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

# HTTPS CDX API 시도
def check_cdx_https(pattern):
    url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={pattern}"
        f"&output=json&fl=timestamp,original,statuscode"
        f"&filter=statuscode:200"
        f"&limit=5"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code == 200:
            data = r.json()
            return data
    except Exception as e:
        return f"ERR: {e}"

# 직접 아카이브 페이지 접근
def fetch_wayback(timestamp, orig_url):
    url = f"https://web.archive.org/web/{timestamp}if_/{orig_url}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        return r.status_code, r.text[:500] if r.status_code == 200 else ""
    except Exception as e:
        return 0, str(e)

print("=== CDX API (HTTPS) ===")
for pattern in [
    "lotteryextreme.com/netherlands/lotto*",
    "lotteryextreme.com/croatia/loto*",
]:
    result = check_cdx_https(pattern)
    print(f"\n{pattern}:")
    print(f"  Result: {result}")

print("\n=== 직접 날짜 테스트 ===")
# 2020년 경 아카이브가 있을 법한 URL들 직접 시도
test_urls = [
    ("20200104000000", "https://www.lotteryextreme.com/netherlands/lotto-results_details(2020-01-04)"),
    ("20190105000000", "https://www.lotteryextreme.com/netherlands/lotto-results_details(2019-01-05)"),
    ("20200108000000", "https://www.lotteryextreme.com/croatia/loto-results_details(2020-01-08)"),
]

for ts, orig in test_urls:
    status, content = fetch_wayback(ts, orig)
    print(f"  HTTP {status}: web.archive.org/web/{ts}/...{orig[-40:]}")
    if status == 200 and "displayball" in content:
        print(f"    ✓ displayball 있음!")
        print(f"    Content: {content[:300]}")
