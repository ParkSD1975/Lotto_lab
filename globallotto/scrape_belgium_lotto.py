"""
Belgium Lotto 2024-03-16 이후 데이터 수집
Source: lotteryextreme.com/belgium/lotto-results_details(YYYY-MM-DD)
"""

import os, csv, time, random, re
from datetime import date, timedelta
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV  = os.path.join(BASE_DIR, "Belgium_Lotto_2024plus.csv")

START_DATE = date(2024, 3, 16)   # 2024-03-13 이후 첫 추첨일(토)
END_DATE   = date(2026, 4, 22)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def all_draw_dates(start: date, end: date):
    """수(2)·토(5) 날짜 생성"""
    d = start
    while d <= end:
        if d.weekday() in (2, 5):   # Wed=2, Sat=5
            yield d
        d += timedelta(days=1)

def fetch_draw(draw_date: date):
    """
    lotteryextreme 개별 날짜 페이지에서 번호 파싱
    반환: (n1,n2,n3,n4,n5,n6, bonus) or None
    """
    url = f"https://www.lotteryextreme.com/belgium/lotto-results_details({draw_date.isoformat()})"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"  [ERR] {draw_date}: {e}")
        return None

    if r.status_code != 200:
        print(f"  [SKIP] {draw_date}: HTTP {r.status_code}")
        return None

    # regex로 직접 파싱 (html.parser의 암묵적 닫기 태그 문제 회피)
    html = r.text

    # displayball ul 찾기
    ul_match = re.search(
        r"<ul[^>]*class=['\"]displayball['\"][^>]*>(.*?)</ul>",
        html, re.DOTALL | re.IGNORECASE
    )
    if not ul_match:
        print(f"  [SKIP] {draw_date}: displayball ul 없음")
        return None

    ul_html = ul_match.group(1)

    # dbx 클래스 기준으로 메인/보너스 분리
    parts = re.split(r'<li[^>]*class=["\'][^"\']*dbx[^"\']*["\'][^>]*>', ul_html, maxsplit=1)
    main_part  = parts[0]
    bonus_part = parts[1] if len(parts) > 1 else ""

    # 각 <li> 바로 뒤 숫자 추출
    main_nums  = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', main_part)]
    bonus_nums = [int(x) for x in re.findall(r'<li[^>]*>(\d+)', bonus_part)]

    if len(main_nums) < 6:
        print(f"  [SKIP] {draw_date}: 번호 부족 ({main_nums})")
        return None

    bonus = bonus_nums[0] if bonus_nums else None
    return tuple(main_nums[:6]) + (bonus,)

def main():
    results = []
    dates = list(all_draw_dates(START_DATE, END_DATE))
    total = len(dates)
    print(f"총 {total}개 날짜 수집 예정 ({START_DATE} ~ {END_DATE})\n")

    for i, d in enumerate(dates, 1):
        row = fetch_draw(d)
        if row:
            n1,n2,n3,n4,n5,n6,bonus = row
            results.append({
                "date": d.isoformat(),
                "n1": n1, "n2": n2, "n3": n3,
                "n4": n4, "n5": n5, "n6": n6,
                "bonus": bonus if bonus else ""
            })
            print(f"[{i:3}/{total}] {d}  {n1}-{n2}-{n3}-{n4}-{n5}-{n6}  B:{bonus}")

        # 요청 간격 (1~2초 랜덤)
        if i < total:
            time.sleep(random.uniform(0.8, 1.8))

    # CSV 저장
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["date","n1","n2","n3","n4","n5","n6","bonus"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✓ {len(results)}건 → {OUT_CSV}")
    print("다음: python -X utf8 import_belgium_2024plus.py")

if __name__ == "__main__":
    main()
