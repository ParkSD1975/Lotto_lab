import re, requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"}
url = "https://www.lotteryextreme.com/belgium/lotto-results_details(2024-03-16)"
r = requests.get(url, headers=HEADERS, timeout=15)
html = r.text

ul_match = re.search(r"<ul[^>]*class=['\"]displayball['\"][^>]*>(.*?)</ul>", html, re.DOTALL | re.IGNORECASE)
if ul_match:
    ul_html = ul_match.group(1)
    print("UL_HTML:", repr(ul_html[:300]))
    parts = re.split(r'<li[^>]*class=["\'][^"\']*dbx[^"\']*["\'][^>]*>', ul_html, maxsplit=1)
    print("Parts count:", len(parts))
    main_nums = [int(x) for x in re.findall(r"<li[^>]*>(\d+)", parts[0])]
    print("Main nums:", main_nums)
    if len(parts) > 1:
        bonus_nums = [int(x) for x in re.findall(r"<li[^>]*>(\d+)", parts[1])]
        print("Bonus nums:", bonus_nums)
else:
    print("NO MATCH - searching for displayball...")
    idx = html.find("displayball")
    if idx >= 0:
        print("Found at:", idx)
        print(repr(html[idx-50:idx+400]))
    else:
        print("Not found at all, HTTP status:", r.status_code)
        print(html[:2000])
