import re
import time
import itertools

# =====================================================================
# 👇 여기에 원하시는 조건을 텍스트 그대로 붙여넣기 하세요! 👇
# =====================================================================
CONDITIONS_TEXT = """
전회차 6 13 18 28 30 36
총합 90 -170
AC값 8
홀짝 : 4:2 3:3 2:4
저고 : 5:1 4:2 3:3 2:4 
번호대 단번대 1-2, 십번대 0-2 이십번대 0-2 삼십번대 1-2 사십번대 0-1
소수 : 2-3
합성수 : 3-5
이월수 : 0-2 (전회차 이월수)
이웃수 : 1-3
14 24 : 0-1
13 15 19 21 44 5 : 1-2
4 5 10 11 12 24 25 26 27 28 35 36 37 38 39 : 1-3
4 5 6 7 8 9 24 25 26 30 31 32 40 41 43 44 45 : 1-3
7 8 9 15 16 17 27 28 29 30 31 32 43 44 45 : 1-3
6 7 8 9 10 23 24 25 26 27 28 34 35 36 37 : 1-3
7 8 9 11 12 13 14 15 16 28 29 30 39 40 41 44 45 : 1-3
2 3 4 27 28 29 30 31 32 33 41 42 43 44 45 : 1-3
7 8 9 10 11 14 15 16 19 20 21 28 29 30 31 32 : 1-3
6 7 8 9 10 18 19 20 22 23 24 25 26 27 44 45 : 1-3
8 9 10 18 19 20 28 29 30 34 35 36 37 38 39 : 1-3
11 15 23 24 28 5 33 : 0-0
4 5 6 12 13 14 25 26 27 36 37 39 40 41 : 1-3
1 2 3 7 8 9 12 13 14 15 16 17 22 23 24 27 28 29 : 1-3
5 6 7 16 17 18 21 22 23 27 28 29 30 31 32 33 : 1- 3
3 4 5 14 15 16 17 18 22 23 24 26 27 28 35 36 37 : 1-3
7 8 9 10 11 13 14 19 20 21 32 33 34 40 41 42 : 1-3
2 3 4 15 16 17 18 19 23 24 25 39 40 41 43 44 45 : 1-3
2 3 4 6 7 8 14 15 16 17 18 19 20 42 43 44 : 1-3
2 3 4 12 13 14 27 28 29 33 34 35 37 38 39 41 42 43 : 2-3
8 9 10 20 21 22 23 24 25 29 30 31 32 33 34 36 37 38 : 2-3
5 6 7 8 26 27 28 29 30 37 38 39 44 45 : 1-3
1 2 8 9 10 11 12 13 14 34 35 36 43 44 45 : 1-3
29 30 31 32 33 34 35 36 37 38 : 1-3
1 2 3 4 8 9 10 14 15 16 26 27 28 29 30 : 1-3
7 8 9 10 17 18 19 34 35 36 38 39 40 44 45 : 1-3
7 8 9 14 15 16 18 19 20 21 22 31 32 33 35 36 37 : 2-3
2 3 4 5 6 7 12 13 14 15 16 17 21 22 23 : 1-3
6 7 8 10 11 12 23 24 25 26 27 28 36 37 38 : 1-3
1 2 3 10 11 12 30 31 32 33 34 36 37 38 43 44 45 : 1-3
2 3 4 5 11 12 13 14 15 16 25 26 27 33 34 35 : 1-3
9 10 11 15 16 17 18 26 27 28 29 35 36 47 : 1-3
1 2 3 7 8 9 27 28 29 30 31 36 37 38 40 41 42 : 1-3
6 7 8 10 11 12 13 20 21 22 25 26 27 34 35 36 : 1-3
6 7 8 9 10 11 21 22 23 28 29 30 31 32 37 38 39 : 1-3
4 5 6 11 12 14 15 16 29 30 31 36 37 38 39 40 41 : 2-3
3 4 5 8 9 10 11 12 13 14 15 16 32 33 34 44 45 : 1-3
2 3 4 6 7 8 9 10 12 13 14 18 19 20 23 24 25 : 1-3
5 6 7 8 18 19 20 27 28 29 33 34 35 40 41 42 : 1-3
4 13 14 15 35 36 37 41 42 : 1-3
1 2 3 4 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 41 42 43 44 45 : 3-4
1 2 3 4 5 6 9 10 11 13 14 15 16 22 23 24 27 28 29 38 39 40 44 45 : 3-4
4 5 6 7 8 9 10 11 14 15 16 19 20 21 24 25 26 28 29 30 31 32 40 41 42 44 45 : 3-5
1 3 6 10 15 21 33 36 45 : 1-2
1 2 3 4 9 10 11 14 15 16 17 18 19 25 26 27 28 29 30 32 33 41 42 43 : 3-5
4 5 6 9 10 11 12 13 15 16 17 20 21 22 23 24 32 33 34 35 36 37 38 39 40 41 : 3-5
"""
# =====================================================================

def calculate_ac(combo):
    diffs = set()
    for i in range(len(combo)):
        for j in range(i + 1, len(combo)):
            diffs.add(abs(combo[i] - combo[j]))
    return len(diffs) - 5

def parse_conditions(text):
    conds = {
        'prev_round': [],
        'min_sum': 0,
        'max_sum': 999,
        'ac': [],
        'odd_counts': [],
        'low_counts': [],
        'ranges': {
            '단번대': (0, 6),
            '십번대': (0, 6),
            '이십번대': (0, 6),
            '삼십번대': (0, 6),
            '사십번대': (0, 6),
        },
        'primes': (0, 6),
        'composites': (0, 6),
        'carry_overs': (0, 6),
        'neighbors': (0, 6),
        'custom_subsets': []
    }
    
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('전회차'):
            conds['prev_round'] = [int(x) for x in re.findall(r'\d+', line)]
            
        elif line.startswith('총합'):
            nums = re.findall(r'\d+', line)
            if len(nums) >= 2:
                conds['min_sum'] = int(nums[0])
                conds['max_sum'] = int(nums[1])
                
        elif line.startswith('AC값'):
            if '-' in line:
                nums = re.findall(r'\d+', line)
                if len(nums) >= 2:
                    conds['ac'] = list(range(int(nums[0]), int(nums[1])+1))
            else:
                nums = re.findall(r'\d+', line)
                conds['ac'] = [int(x) for x in nums]
                
        elif line.startswith('홀짝'):
            pairs = re.findall(r'(\d+):(\d+)', line)
            conds['odd_counts'] = [int(odd) for odd, even in pairs]
            
        elif line.startswith('저고'):
            pairs = re.findall(r'(\d+):(\d+)', line)
            conds['low_counts'] = [int(low) for low, high in pairs]
            
        elif line.startswith('번호대'):
            for group in ['단번대', '십번대', '이십번대', '삼십번대', '사십번대']:
                match = re.search(group + r'\s*(\d+)(?:\s*-\s*(\d+))?', line)
                if match:
                    min_val = int(match.group(1))
                    max_val = int(match.group(2)) if match.group(2) else min_val
                    conds['ranges'][group] = (min_val, max_val)
                    
        elif line.startswith('소수'):
            right_part = line.split(':')[-1] if ':' in line else line
            nums = re.findall(r'\d+', right_part)
            if len(nums) >= 2:
                conds['primes'] = (int(nums[0]), int(nums[1]))
            elif len(nums) == 1:
                conds['primes'] = (int(nums[0]), int(nums[0]))
                
        elif line.startswith('합성수'):
            right_part = line.split(':')[-1] if ':' in line else line
            nums = re.findall(r'\d+', right_part)
            if len(nums) >= 2:
                conds['composites'] = (int(nums[0]), int(nums[1]))
            elif len(nums) == 1:
                conds['composites'] = (int(nums[0]), int(nums[0]))
                
        elif line.startswith('이월수'):
            right_part = line.split(':')[-1] if ':' in line else line
            right_part = right_part.split('(')[0]
            nums = re.findall(r'\d+', right_part)
            if len(nums) >= 2:
                conds['carry_overs'] = (int(nums[0]), int(nums[1]))
            elif len(nums) == 1:
                conds['carry_overs'] = (int(nums[0]), int(nums[0]))
                
        elif line.startswith('이웃수'):
            right_part = line.split(':')[-1] if ':' in line else line
            nums = re.findall(r'\d+', right_part)
            if len(nums) >= 2:
                conds['neighbors'] = (int(nums[0]), int(nums[1]))
            elif len(nums) == 1:
                conds['neighbors'] = (int(nums[0]), int(nums[0]))
                
        else:
            if ':' in line:
                left, right = line.split(':', 1)
                subset_nums = [int(x) for x in re.findall(r'\d+', left)]
                ranges = [int(x) for x in re.findall(r'\d+', right)]
                
                if any(k in left for k in ['홀짝', '저고', '소수', '합성수', '이월수', '이웃수']):
                    continue
                    
                if subset_nums and ranges:
                    min_val = ranges[0]
                    max_val = ranges[1] if len(ranges) >= 2 else min_val
                    conds['custom_subsets'].append((subset_nums, min_val, max_val))
                    
    return conds

def generate(conds):
    primes_set = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
    composites_set = set(range(1, 46)) - primes_set - {1}
    prev_set = set(conds['prev_round'])
    
    # [수정] 이웃수: 전회차 번호의 ±1에 해당하는 번호 집합
    neighbors_set = set()
    for x in conds['prev_round']:
        if x > 1: neighbors_set.add(x - 1)
        if x < 45: neighbors_set.add(x + 1)
    # 이웃수에서 전회차 번호 자체는 제외 (이월수와 중복 방지)
    neighbors_set -= prev_set
    
    results = []
    total = 0
    
    print("⏳ 1~45에서 6개를 뽑는 모든 경우의 수(약 814만 개)를 전수조사 중입니다...")
    print("   (보통 10~30초 내외 소요됩니다. 잠시만 기다려 주세요!)\n")
    
    start_time = time.time()
    r = conds['ranges']
    
    # [수정] itertools.combinations로 가능한 모든 조합을 빠짐없이 순회
    for combo in itertools.combinations(range(1, 46), 6):
        total += 1
        
        # 총합
        s = sum(combo)
        if not (conds['min_sum'] <= s <= conds['max_sum']): continue
        
        # AC
        if conds['ac'] and (calculate_ac(combo) not in conds['ac']): continue
            
        # 홀짝
        if conds['odd_counts']:
            odd = sum(1 for x in combo if x % 2 != 0)
            if odd not in conds['odd_counts']: continue
            
        # 저고 (저: 1~22, 고: 23~45)
        if conds['low_counts']:
            low = sum(1 for x in combo if x <= 22)
            if low not in conds['low_counts']: continue
            
        # 번호대
        dan = sum(1 for x in combo if x <= 9)
        if not (r['단번대'][0] <= dan <= r['단번대'][1]): continue
        
        sip = sum(1 for x in combo if 10 <= x <= 19)
        if not (r['십번대'][0] <= sip <= r['십번대'][1]): continue
        
        isip = sum(1 for x in combo if 20 <= x <= 29)
        if not (r['이십번대'][0] <= isip <= r['이십번대'][1]): continue
        
        sam = sum(1 for x in combo if 30 <= x <= 39)
        if not (r['삼십번대'][0] <= sam <= r['삼십번대'][1]): continue
        
        sa = sum(1 for x in combo if 40 <= x <= 45)
        if not (r['사십번대'][0] <= sa <= r['사십번대'][1]): continue
        
        # 소수
        p_count = sum(1 for x in combo if x in primes_set)
        if not (conds['primes'][0] <= p_count <= conds['primes'][1]): continue
        
        # 합성수
        c_count = sum(1 for x in combo if x in composites_set)
        if not (conds['composites'][0] <= c_count <= conds['composites'][1]): continue
        
        # 이월수
        if prev_set:
            carry_count = sum(1 for x in combo if x in prev_set)
            if not (conds['carry_overs'][0] <= carry_count <= conds['carry_overs'][1]): continue
            
        # 이웃수
        if neighbors_set:
            n_count = sum(1 for x in combo if x in neighbors_set)
            if not (conds['neighbors'][0] <= n_count <= conds['neighbors'][1]): continue
            
        # 커스텀 지정수 그룹
        passed_subsets = True
        for subset, min_val, max_val in conds['custom_subsets']:
            count_sub = sum(1 for x in combo if x in set(subset))
            if not (min_val <= count_sub <= max_val):
                passed_subsets = False
                break
        if not passed_subsets: continue
        
        results.append(list(combo))
            
    elapsed = time.time() - start_time
    return results, total, elapsed

if __name__ == "__main__":
    print("=== 🎲 로또 조건 완전탐색 시작 ===\n")
    conds = parse_conditions(CONDITIONS_TEXT)
    
    # [수정] 전수조사 방식 - count 파라미터 없음 (조건에 맞는 것 전부 출력)
    combos, total_checked, elapsed = generate(conds)
    
    print(f"✅ 전수조사 완료! ({elapsed:.2f}초 소요, 총 {total_checked:,}개 조합 검사)")
    print("==========================================")
    if not combos:
        print("😥 조건에 맞는 조합을 단 하나도 찾지 못했습니다.")
        print("조건(비율이나 갯수 범위)을 조금만 더 넉넉하게 변경해 보세요.")
    else:
        print(f"🎯 조건에 맞는 조합: 총 {len(combos):,}개\n")
        for i, combo in enumerate(combos, 1):
            # [수정] 번호만 출력 (합계/홀짝/AC 정보 제거)
            print(f"[{i:>5}] {combo}")
