"""Wayback Machine CDX - 더 넓은 패턴으로 검색"""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}

patterns = [
    "lotteryextreme.com/netherlands*",
    "lotteryextreme.com/croatia*",
    "lotteryextreme.com/netherlands/lotto*",
    "lotteryextreme.com/croatia/loto*",
]

for pattern in patterns:
    cdx_url = (
        f"http://web.archive.org/cdx/search/cdx"
        f"?url={pattern}"
        f"&output=json&fl=timestamp,original,statuscode"
        f"&limit=10&collapse=urlkey"
    )
    r = requests.get(cdx_url, headers=HEADERS, timeout=30)
    data = r.json()
    count = len(data) - 1 if data else 0
    print(f"\nPattern: {pattern}")
    print(f"  Captures: {count}")
    if count > 0:
        for item in data[1:4]:
            print(f"  {item}")
