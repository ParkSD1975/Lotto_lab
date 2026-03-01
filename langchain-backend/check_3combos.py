# -*- coding: utf-8 -*-
import math

combos = [[5,12,15,24,25,30], [5,12,15,24,25,39], [5,12,15,24,25,42]]

GARO = {
    '가로1':{1,2,3,4,5,6,7},'가로2':{8,9,10,11,12,13,14},'가로3':{15,16,17,18,19,20,21},
    '가로4':{22,23,24,25,26,27,28},'가로5':{29,30,31,32,33,34,35},
    '가로6':{36,37,38,39,40,41,42},'가로7':{43,44,45}
}
SERO = {
    '세로1':{1,8,15,22,29,36,43},'세로2':{2,9,16,23,30,37,44},
    '세로3':{3,10,17,24,31,38,45},'세로4':{4,11,18,25,32,39},
    '세로5':{5,12,19,26,33,40},'세로6':{6,13,20,27,34,41},'세로7':{7,14,21,28,35,42}
}
PAPER_S = {
    '가로1':(0,2),'가로2':(0,1),'가로3':(1,2),'가로4':(0,3),'가로5':(0,2),
    '가로6':(0,3),'가로7':(0,1),'세로1':(0,1),'세로2':(0,3),'세로3':(1,3),
    '세로4':(0,2),'세로5':(0,2),'세로6':(1,2),'세로7':(0,1)
}
PALACE = {
    '1궁':{1,2,3,4,5},'2궁':{6,7,8,9,10},'3궁':{11,12,13,14,15},
    '4궁':{16,17,18,19,20},'5궁':{21,22,23,24,25},'6궁':{26,27,28,29,30},
    '7궁':{31,32,33,34,35},'8궁':{36,37,38,39,40},'9궁':{41,42,43,44,45}
}
MULTIPLES = {
    '3배수':{3,6,9,12,15,18,21,24,27,30,33,36,39,42,45},
    '4배수':{4,8,12,16,20,24,28,32,36,40,44},
    '5배수':{5,10,15,20,25,30,35,40,45},
    '3·4배수':{12,24,36},'3·5배수':{15,30,45},'4·5배수':{20,40},
    '배수외':{1,2,7,11,13,14,17,19,22,23,26,29,31,34,37,38,41,43}
}
MULT_S = {'3배수':(1,4),'4배수':(1,2),'5배수':(1,2),'배수외':(2,5),
          '3·4배수':(0,1),'3·5배수':(0,1),'4·5배수':(0,1)}

TAIL_S = {0:(0,1),1:(0,3),2:(0,1),3:(0,1),4:(0,1),5:(0,2),6:(0,2),7:(0,3),8:(0,2),9:(0,1)}

PRIMES_ALL = {2,3,5,7,11,13,17,19,23,29,31,37,41,43}
SQUARES_ALL = {1,4,9,16,25,36}
TRIANGULARS_ALL = {1,3,6,10,15,21,28,36,45}
TWINS_ALL = {11,22,33,44}

def entropy_val(nums):
    ranges = [
        sum(1 for n in nums if 1<=n<=10),
        sum(1 for n in nums if 11<=n<=20),
        sum(1 for n in nums if 21<=n<=30),
        sum(1 for n in nums if 31<=n<=40),
        sum(1 for n in nums if 41<=n<=45)
    ]
    h = 0
    for c in ranges:
        if c > 0:
            h -= (c/6)*math.log2(c/6)
    return round(h, 3)

for combo in combos:
    s = set(combo)
    print(f"\n{'='*55}")
    print(f"조합: {combo}")
    print(f"{'='*55}")

    # 1. 고정수/제외수 (바스켓) - 없음
    print(f"1. 고정수/제외수(바스켓): 없음 → ✅ 해당없음")

    # 2. 총합 제외 합계
    tot = sum(combo)
    # excludedSums=[], restoredAutoSums=[189,179,166] → 현재 제외 없음
    excl_sums = []  # 실제 제외 합계
    sum_ok = tot not in excl_sums and 99 <= tot <= 189
    print(f"2. 총합={tot} (99-189, excludedSums=[]): {'✅' if sum_ok else '❌'}")

    # 3. 끝수합 32 제외 여부
    lds = sum(n % 10 for n in combo)
    # autoExcluded=[32], restoredAutoSums=[32] → 32가 복원됨(제외 아님) vs 여전히 제외
    lds_excl_yes = (16 <= lds <= 39) and (lds != 32)
    lds_excl_no  = (16 <= lds <= 39)
    print(f"3. 끝수합={lds}: 32제외 적용시={'✅' if lds_excl_yes else '❌'} / 32제외 미적용시={'✅' if lds_excl_no else '❌'}")

    # 4. 끝수(tail_digit) 적용
    tc = {}
    for n in combo:
        tc[n % 10] = tc.get(n % 10, 0) + 1
    td_fails = []
    for d, (mn, mx) in TAIL_S.items():
        cnt = tc.get(d, 0)
        if not (mn <= cnt <= mx):
            td_fails.append(f"끝수{d}={cnt}개(max:{mx})")
    print(f"4. 끝수패턴: {'✅' if not td_fails else '❌ ' + ', '.join(td_fails)}")

    # 5. AC값 8 제외
    nums_s = sorted(combo)
    diffs = set()
    for i in range(6):
        for j in range(i+1, 6):
            diffs.add(nums_s[j]-nums_s[i])
    ac = len(diffs) - 5
    print(f"5. AC값={ac} (7-9, 8제외): {'✅' if 7<=ac<=9 and ac!=8 else '❌'}")

    # 6. 소수 제외(17번) 및 개수 [0,1,2,3]
    incl_17 = 17 in s
    pc = sum(1 for n in combo if n in PRIMES_ALL)
    print(f"6. 소수: 17포함={'❌' if incl_17 else '✅없음'}, 소수개수={pc}(0-3허용)={'✅' if pc<=3 else '❌'}")

    # 7. 제곱수 [0,1] + 36제외
    incl_36 = 36 in s
    sq = sum(1 for n in combo if n in SQUARES_ALL)
    print(f"7a. 제곱수: 36포함={'❌' if incl_36 else '✅없음'}, 개수={sq}(0-1): {'✅' if sq<=1 else '❌'}")

    # 삼각수 [0,1,2]
    tri = sum(1 for n in combo if n in TRIANGULARS_ALL)
    print(f"7b. 삼각수={tri}개(0-2허용): {'✅' if tri<=2 else '❌'}")

    # 동형수(twin) [0,1] + 44제외
    incl_44 = 44 in s
    tw = sum(1 for n in combo if n in TWINS_ALL)
    print(f"7c. 동형수: 44포함={'❌' if incl_44 else '✅없음'}, 개수={tw}(0-1): {'✅' if tw<=1 else '❌'}")

    # 이웃수 (1211회 [23,26,27,35,38,40]의 이웃)
    prev_nums = {23,26,27,35,38,40}
    nbrs = set()
    for n in prev_nums:
        if n > 1: nbrs.add(n-1)
        if n < 45: nbrs.add(n+1)
    nbrs -= prev_nums
    nb_cnt = sum(1 for n in combo if n in nbrs)
    print(f"7d. 이웃수={nb_cnt}개(0-3허용): {'✅' if nb_cnt<=3 else '❌'}")

    # 이월수 (1211회 [23,26,27,35,38,40], selectedCounts=[0,1,2])
    carry_nums = {23,26,27,35,38,40}
    carry_cnt = sum(1 for n in combo if n in carry_nums)
    print(f"7e. 이월수={carry_cnt}개([0,1,2]허용): {'✅' if carry_cnt in {0,1,2} else '❌'}")

    # 연번 [0,1], 3연속 금지
    consec = sum(1 for i in range(5) if nums_s[i+1]-nums_s[i]==1)
    has3 = any(nums_s[i+1]-nums_s[i]==1 and nums_s[i+2]-nums_s[i+1]==1 for i in range(4))
    print(f"7f. 연번={consec}개(0-1허용), 3연속={'있음❌' if has3 else '없음✅'}")

    # 배수 패턴
    mult_fails = []
    for m, (mn, mx) in MULT_S.items():
        cnt = sum(1 for n in combo if n in MULTIPLES[m])
        if not (mn <= cnt <= mx):
            mult_fails.append(f"{m}={cnt}개(허용{mn}-{mx})")
    print(f"7g. 배수패턴: {'✅' if not mult_fails else '❌ ' + ', '.join(mult_fails)}")

    # 9궁 (3궁 min:1)
    p_fails = []
    for p, ns in PALACE.items():
        mn = 1 if p == '3궁' else 0
        cnt = sum(1 for n in combo if n in ns)
        if not (mn <= cnt <= 2):
            p_fails.append(f"{p}={cnt}")
    print(f"7h. 9궁: {'✅' if not p_fails else '❌ ' + ', '.join(p_fails)}")

    # 로또용지
    all_grp = {**GARO, **SERO}
    pf = []
    for g, (mn, mx) in PAPER_S.items():
        cnt = sum(1 for n in combo if n in all_grp[g])
        if not (mn <= cnt <= mx):
            pf.append(f"{g}={cnt}(min:{mn})")
    print(f"7i. 로또용지: {'✅' if not pf else '❌ ' + ', '.join(pf)}")

    # 미출현커스텀
    CUST1 = {1,2,3,4,5,6,7,8,9,10,16,17,18,20,22,23,24,25,26,27,28,29,30,31,35,36,37,38,39,40,41,42,44,45}
    CUST2 = {11,12,13,14,15,19,21,32,33,34,43}
    cg1 = sum(1 for n in combo if n in CUST1)
    cg2 = sum(1 for n in combo if n in CUST2)
    print(f"7j. 미출현커스텀: G1={cg1}(2-6허용)={'✅' if 2<=cg1<=6 else '❌'}, G2={cg2}(1-3허용)={'✅' if 1<=cg2<=3 else '❌'}")

    # 8. 엔트로피
    h = entropy_val(combo)
    print(f"8. 엔트로피={h}(1-2.25허용): {'✅' if 1<=h<=2.25 else '❌'}")

    # 번호대 범위
    r1=sum(1 for n in combo if 1<=n<=10)
    r2=sum(1 for n in combo if 11<=n<=20)
    r3=sum(1 for n in combo if 21<=n<=30)
    r4=sum(1 for n in combo if 31<=n<=40)
    r5=sum(1 for n in combo if 41<=n<=45)
    rng_ok = (0<=r1<=3 and 1<=r2<=2 and 0<=r3<=3 and 0<=r4<=3 and 0<=r5<=2)
    print(f"   번호대: 1-10={r1}, 11-20={r2}, 21-30={r3}, 31-40={r4}, 41-45={r5} → {'✅' if rng_ok else '❌'}")

    # 9. 커스텀분석(missing_custom) - 위 7j와 동일
    print(f"9. 커스텀분석(미출현커스텀): G1={cg1}, G2={cg2} → 위 7j 참조")
