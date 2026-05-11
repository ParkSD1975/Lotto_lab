import os, sys, requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def test_guru(country_path, slug):
    url = f"https://lotteryguru.com/{country_path}/{slug}/{slug}-results-history?page=1"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    line = soup.select_one("div.lg-line")
    for div in line.select("div.lg-date"):
        print(f"Div: {div.get_text(strip=True)}")

test_guru("austria-lottery-results", "at-lotto")
