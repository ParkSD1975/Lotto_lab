"""Croatia / Hungary / Netherlands lotteryextreme URL 패턴 테스트"""
import re, requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}

tests = [
    ("Netherlands",  "https://www.lotteryextreme.com/netherlands/lotto-results_details(2024-01-06)"),
    ("Hungary",      "https://www.lotteryextreme.com/hungary/hatoslotto-results_details(2024-01-04)"),
    ("Croatia",      "https://www.lotteryextreme.com/croatia/loto-results_details(2024-01-10)"),
]

def parse_nums(html):
    ul_match = re.search(r"<ul[^>]*class=['\"]displayball['\"][^>]*>(.*?)</ul>", html, re.DOTALL|re.IGNORECASE)
    if not ul_match:
        return None, None
    ul_html = ul_match.group(1)
    parts = re.split(r'<li[^>]*class=["\'][^"\']*dbx[^"\']*["\'][^>]*>', ul_html, maxsplit=1)
    main_nums = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', parts[0])]
    bonus_nums = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', parts[1])] if len(parts)>1 else []
    return main_nums, bonus_nums

for name, url in tests:
    r = requests.get(url, headers=HEADERS, timeout=15)
    print(f"\n{name}: HTTP {r.status_code}  URL={url}")
    if r.status_code == 200:
        main, bonus = parse_nums(r.text)
        print(f"  Main: {main}  Bonus: {bonus}")
    else:
        # 페이지 일부 출력
        print(f"  Response: {r.text[:200]}")
