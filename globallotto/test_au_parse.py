"""au.lottonumbers.com 파서 테스트 - 2023년 1개 연도"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from scrape_australia_lotto import scrape_year

rows = scrape_year("saturday-lotto", 2023)
print(f"2023 Saturday Lotto: {len(rows)}건")
for r in rows[:5]:
    print(r)
