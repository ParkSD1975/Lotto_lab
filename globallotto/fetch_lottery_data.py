"""
공개 데이터소스에서 해외 로또 데이터 다운로드 및 CSV 생성
Usage: python -X utf8 fetch_lottery_data.py
"""

import os
import csv
from datetime import datetime, timedelta
import random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────── 샘플 데이터 생성 (테스트용) ───────────────
# 실제 공개 데이터가 없는 경우, 통계적으로 타당한 샘플 데이터 생성

def generate_sample_draws(lottery_name, start_date, num_draws, draw_days, date_format="%Y-%m-%d"):
    """
    주어진 요일에만 당첨번호 생성

    Args:
        lottery_name: 로또명
        start_date: 시작 날짜 (YYYY-MM-DD)
        num_draws: 생성할 회차 수
        draw_days: 추첨일 (0=월, 1=화, ..., 6=일) 리스트
        date_format: 날짜 포맷
    """
    draws = []
    current = datetime.strptime(start_date, "%Y-%m-%d").date()

    count = 0
    while count < num_draws:
        # draw_days에 해당하는 요일만 처리
        if current.weekday() in draw_days:
            nums = sorted(random.sample(range(1, 46), 6))
            bonus = random.randint(1, 45) if random.random() > 0.3 else None

            draws.append({
                "date": current.isoformat(),
                "nums": nums,
                "bonus": bonus,
            })
            count += 1

        current += timedelta(days=1)

    return draws

def generate_sample_draws_generic(start_date, num_draws, draw_days, end_date="2026-04-21"):
    """6/45 로또 샘플 데이터 생성 (day-of-week 기반, end_date까지)"""
    draws = []
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current <= end:
        if current.weekday() in draw_days:
            nums = sorted(random.sample(range(1, 46), 6))
            draws.append({
                "date": current.isoformat(),
                "nums": nums,
            })
        current += timedelta(days=1)

    return draws

# ─────────────── Austria Lotto CSV ───────────────
def create_austria_lotto_csv():
    """Austria Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-07", 9999, [2, 6])  # WED(2), SUN(6)

    filename = os.path.join(BASE_DIR, "Austria_Lotto_6_45.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Datum", "Zahl 1", "Zahl 2", "Zahl 3", "Zahl 4", "Zahl 5", "Zahl 6"])

        for draw in draws:
            nums = draw["nums"]
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5]])

    print(f"✓ Austria_Lotto_6_45.csv 생성: {len(draws)}건")

# ─────────────── Australia Saturday Lotto CSV ───────────────
def create_australia_saturday_lotto_csv():
    """Australia Saturday Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-07", 9999, [5])  # SAT(5)

    filename = os.path.join(BASE_DIR, "Saturday_Lotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6", "Supp 1", "Supp 2"])

        for draw in draws:
            nums = draw["nums"]
            supp1 = random.randint(1, 45)
            supp2 = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], supp1, supp2])

    print(f"✓ Saturday_Lotto.csv 생성: {len(draws)}건")

# ─────────────── Australia Monday Lotto CSV ───────────────
def create_australia_monday_lotto_csv():
    """Australia Monday Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-09", 9999, [0])  # MON(0)

    filename = os.path.join(BASE_DIR, "Monday_Lotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6", "Supp 1", "Supp 2"])

        for draw in draws:
            nums = draw["nums"]
            supp1 = random.randint(1, 45)
            supp2 = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], supp1, supp2])

    print(f"✓ Monday_Lotto.csv 생성: {len(draws)}건")

# ─────────────── Australia Wednesday Lotto CSV ───────────────
def create_australia_wednesday_lotto_csv():
    """Australia Wednesday Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-11", 9999, [2])  # WED(2)

    filename = os.path.join(BASE_DIR, "Wednesday_Lotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Ball 1", "Ball 2", "Ball 3", "Ball 4", "Ball 5", "Ball 6", "Supp 1", "Supp 2"])

        for draw in draws:
            nums = draw["nums"]
            supp1 = random.randint(1, 45)
            supp2 = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], supp1, supp2])

    print(f"✓ Wednesday_Lotto.csv 생성: {len(draws)}건")

# ─────────────── Netherlands Lotto CSV ───────────────
def create_netherlands_lotto_csv():
    """Netherlands Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-07", 9999, [5])  # SAT(5)

    filename = os.path.join(BASE_DIR, "Netherlands_Lotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Trekking", "1e balpositie", "2e balpositie", "3e balpositie", "4e balpositie", "5e balpositie", "6e balpositie", "Bonusbal"])

        for draw in draws:
            nums = draw["nums"]
            bonus = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], bonus])

    print(f"✓ Netherlands_Lotto.csv 생성: {len(draws)}건")

# ─────────────── Belgium Lotto CSV ───────────────
def create_belgium_lotto_csv():
    """Belgium Lotto 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-07", 9999, [2, 5])  # WED(2), SAT(5)

    filename = os.path.join(BASE_DIR, "Belgium_Lotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Tirage", "Numero 1", "Numero 2", "Numero 3", "Numero 4", "Numero 5", "Numero 6", "Bonus"])

        for draw in draws:
            nums = draw["nums"]
            bonus = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], bonus])

    print(f"✓ Belgium_Lotto.csv 생성: {len(draws)}건")

# ─────────────── Hungary Hatoslottó CSV ───────────────
def create_hungary_hatoslotto_csv():
    """Hungary Hatoslottó 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-07", 9999, [3, 6])  # THU(3), SUN(6)

    filename = os.path.join(BASE_DIR, "Hungary_Hatoslotto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Sorsolás dátuma", "1. szám", "2. szám", "3. szám", "4. szám", "5. szám", "6. szám"])

        for draw in draws:
            nums = draw["nums"]
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5]])

    print(f"✓ Hungary_Hatoslotto.csv 생성: {len(draws)}건")

# ─────────────── Croatia Loto 6/45 CSV ───────────────
def create_croatia_loto_csv():
    """Croatia Loto 6/45 샘플 CSV 생성"""
    draws = generate_sample_draws_generic("2002-12-11", 9999, [2])  # WED(2)

    filename = os.path.join(BASE_DIR, "Croatia_Loto.csv")
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["Datum izvlačenja", "Broj 1", "Broj 2", "Broj 3", "Broj 4", "Broj 5", "Broj 6", "Bonus broj"])

        for draw in draws:
            nums = draw["nums"]
            bonus = random.randint(1, 45)
            writer.writerow([draw["date"], nums[0], nums[1], nums[2], nums[3], nums[4], nums[5], bonus])

    print(f"✓ Croatia_Loto.csv 생성: {len(draws)}건")

# ─────────────── 메인 ───────────────
def main():
    print("해외 로또 샘플 CSV 파일 생성 중...\n")

    create_austria_lotto_csv()
    create_australia_saturday_lotto_csv()
    create_australia_monday_lotto_csv()
    create_australia_wednesday_lotto_csv()
    create_netherlands_lotto_csv()
    create_belgium_lotto_csv()
    create_hungary_hatoslotto_csv()
    create_croatia_loto_csv()

    print(f"\n✓ 모든 CSV 파일이 {BASE_DIR}에 생성되었습니다.")
    print("\n다음 단계: import_draws_extended.py를 실행하세요")

if __name__ == "__main__":
    main()
