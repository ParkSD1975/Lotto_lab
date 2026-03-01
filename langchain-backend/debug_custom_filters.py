# -*- coding: utf-8 -*-
"""
10개 생존 조합에서 어느 커스텀 필터가 제거하는지 디버그
"""
from itertools import combinations
from supabase import create_client
import math

SUPABASE_URL = 'https://dkcflmyoscudawleglzb.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo'
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

res = sb.table('lotto_draws').select('round,date,numbers,bonus').order('round', desc=True).limit(220).execute()
all_draws_raw = res.data
TARGET_ROUND = 1212
prev_draws = [d for d in all_draws_raw if d['round'] < TARGET_ROUND]
prev_draws.sort(key=lambda x: x['round'], reverse=True)

prev1_nums = list(prev_draws[0]['numbers'])
prev2_nums = list(prev_draws[1]['numbers'])
carryover_nums = set(prev_draws[0]['numbers'])

print(f"전회차(1211): {prev1_nums}")
print(f"2전회차(1210): {prev2_nums}")

PRIMES = {2,3,5,7,11,13,17,19,23,29,31,37,41,43}
SQUARES = {1,4,9,16,25,36}
TRIANGULARS = {1,3,6,10,15,21,28,36,45}
TWINS = {11,22,33,44}
COMPOSITES = {4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,32,33,34,35,36,38,39,40,42,44,45}
GARO = {'가로1':{1,2,3,4,5,6,7},'가로2':{8,9,10,11,12,13,14},'가로3':{15,16,17,18,19,20,21},'가로4':{22,23,24,25,26,27,28},'가로5':{29,30,31,32,33,34,35},'가로6':{36,37,38,39,40,41,42},'가로7':{43,44,45}}
SERO = {'세로1':{1,8,15,22,29,36,43},'세로2':{2,9,16,23,30,37,44},'세로3':{3,10,17,24,31,38,45},'세로4':{4,11,18,25,32,39},'세로5':{5,12,19,26,33,40},'세로6':{6,13,20,27,34,41},'세로7':{7,14,21,28,35,42}}
PALACE = {'1궁':{1,2,3,4,5},'2궁':{6,7,8,9,10},'3궁':{11,12,13,14,15},'4궁':{16,17,18,19,20},'5궁':{21,22,23,24,25},'6궁':{26,27,28,29,30},'7궁':{31,32,33,34,35},'8궁':{36,37,38,39,40},'9궁':{41,42,43,44,45}}
MULTIPLES = {'3배수':{3,6,9,12,15,18,21,24,27,30,33,36,39,42,45},'4배수':{4,8,12,16,20,24,28,32,36,40,44},'5배수':{5,10,15,20,25,30,35,40,45},'3.4배수':{12,24,36},'3.5배수':{15,30,45},'4.5배수':{20,40},'배수외':{1,2,7,11,13,14,17,19,22,23,26,29,31,34,37,38,41,43}}

def wrap(n):
    while n > 45: n -= 45
    while n < 1: n += 45
    return n

def off(src, v):
    return set(wrap(n + v) for n in src)

CUSTOM_FILTERS = [
    ('2전회차+2',     off(prev2_nums, +2), 0, 2),
    ('당첨일 끝수',   {1,11,21,31,41},     0, 1),
    ('2전회차+3',     off(prev2_nums, +3), 0, 2),
    ('전회차+1',      off(prev1_nums, +1), 0, 1),
    ('전회차-2',      off(prev1_nums, -2), 0, 2),
    ('2전회차-3',     off(prev2_nums, -3), 0, 1),
    ('전회차+4',      off(prev1_nums, +4), 1, 3),
    ('전회차-1',      off(prev1_nums, -1), 0, 2),
    ('전회차-3',      off(prev1_nums, -3), 1, 3),
    ('카탈량수',      {1,2,5,14,42},       0, 1),
    ('2전회차-1',     off(prev2_nums, -1), 0, 2),
    ('전회차+3',      off(prev1_nums, +3), 1, 2),
    ('2전회차-2',     off(prev2_nums, -2), 0, 2),
    ('전회차+5',      off(prev1_nums, +5), 0, 2),
    ('추첨일사칙',    {1,2,5,6,10,13,18,19,20,21,22,23,24,26,28,40,41,42}, 1, 3),
    ('전회차-4',      off(prev1_nums, -4), 0, 2),
    ('전회차-5',      off(prev1_nums, -5), 0, 2),
    ('전회차+7',      off(prev1_nums, +7), 0, 2),
    ('2전회차+1',     off(prev2_nums, +1), 0, 2),
    ('전회차+2',      off(prev1_nums, +2), 1, 3),
    ('하샤드수',      {1,2,3,4,5,6,7,8,9,10,12,18,20,21,24,27,30,36,40,42,45}, 2, 5),
    ('전회차x2',      set(wrap(n*2) for n in prev1_nums), 0, 2),
    ('딥러닝제외수',  {2,9,17,25,27,31,32,35,38,41}, 1, 2),
    ('피보나치',      {1,2,3,5,8,13,21,34,45}, 1, 2),
    ('딥러닝추천수',  {11,12,13,15,34},     0, 2),
    ('회차끝수',      {2,12,22,32,42},      0, 1),
    ('루카스수',      {1,3,4,7,11,18,29},   1, 2),
    ('전회차÷2',      set(round(n/2) for n in prev1_nums), 0, 2),
    ('회차-1끝수',    {1,11,21,31,41},      0, 2),
]

print("\n커스텀 필터 대상 번호:")
for name, targets, mn, mx in CUSTOM_FILTERS:
    print(f"  [{mn}-{mx}] {name}: {sorted(targets)}")

def calc_ac(nums):
    diffs = set()
    s = sorted(nums)
    for i in range(len(s)):
        for j in range(i+1, len(s)): diffs.add(s[j]-s[i])
    return len(diffs)-(len(nums)-1)

def entropy_val(nums):
    ranges=[sum(1 for n in nums if 1<=n<=10),sum(1 for n in nums if 11<=n<=20),
            sum(1 for n in nums if 21<=n<=30),sum(1 for n in nums if 31<=n<=40),
            sum(1 for n in nums if 41<=n<=45)]
    h = 0
    for c in ranges:
        if c > 0: h -= (c/6)*math.log2(c/6)
    return round(h, 3)

PAPER_S = {'가로1':(0,2),'가로2':(0,1),'가로3':(1,2),'가로4':(0,3),'가로5':(0,2),'가로6':(0,3),'가로7':(0,1),'세로1':(0,1),'세로2':(0,3),'세로3':(1,3),'세로4':(0,2),'세로5':(0,2),'세로6':(1,2),'세로7':(0,1)}
PALACE_S = {p:(1 if p=='3궁' else 0, 2) for p in PALACE}
MULT_S = {'3배수':(1,4),'4배수':(1,2),'5배수':(1,2),'배수외':(2,5),'3.4배수':(0,1),'3.5배수':(0,1),'4.5배수':(0,1)}
TAIL_S = {0:(0,1),1:(0,3),2:(0,1),3:(0,1),4:(0,1),5:(0,2),6:(0,2),7:(0,3),8:(0,2),9:(0,1)}
HOT5_S  = {'hotMin':0,'hotMax':1,'coldMin':1,'coldMax':6,'neutralMin':0,'neutralMax':4}
HOT10_S = {'hotMin':0,'hotMax':3,'coldMin':0,'coldMax':3,'neutralMin':3,'neutralMax':6}
HOT15_S = {'hotMin':0,'hotMax':2,'coldMin':0,'coldMax':4,'neutralMin':1,'neutralMax':5}
HOT20_S = {'hotMin':0,'hotMax':2,'coldMin':0,'coldMax':3,'neutralMin':3,'neutralMax':6}
MISS_S  = {'r1':{'min':2,'max':6},'r2':{'min':1,'max':3},'r3':{'min':0,'max':1},'r4':{'min':1,'max':2}}
CUST1 = {1,2,3,4,5,6,7,8,9,10,16,17,18,20,22,23,24,25,26,27,28,29,30,31,35,36,37,38,39,40,41,42,44,45}
CUST2 = {11,12,13,14,15,19,21,32,33,34,43}

def get_hc(draws, n):
    freq = {i:0 for i in range(1, 46)}
    for d in draws[:n]:
        for num in d['numbers']: freq[num] += 1
    s = sorted(freq, key=lambda x: freq[x], reverse=True)
    top15 = set(s[:15]); bot15 = set(s[30:])
    return top15, bot15, set(range(1,46))-top15-bot15

hot5,cold5,neutral5 = get_hc(prev_draws, 5)
hot10,cold10,neutral10 = get_hc(prev_draws, 10)
hot15,cold15,neutral15 = get_hc(prev_draws, 15)
hot20,cold20,neutral20 = get_hc(prev_draws, 20)

def calc_miss(dl):
    miss = {}; found = set()
    for i, d in enumerate(dl):
        for n in d['numbers']:
            if n not in found: miss[n] = i+1; found.add(n)
    for n in range(1, 46):
        if n not in miss: miss[n] = len(dl)+1
    return miss

miss_periods = calc_miss(prev_draws[:50])
miss_g1=set(); miss_g2=set(); miss_g3=set(); miss_g4=set()
for n in range(1, 46):
    m = miss_periods.get(n, 999)
    if m<=5: miss_g1.add(n)
    elif m<=10: miss_g2.add(n)
    elif m<=15: miss_g3.add(n)
    else: miss_g4.add(n)

neighbors = set()
for n in carryover_nums:
    if n > 1: neighbors.add(n-1)
    if n < 45: neighbors.add(n+1)
neighbors -= carryover_nums

def passes_foundation(nums):
    s = set(nums)
    ac = calc_ac(nums)
    if ac < 7 or ac > 9 or ac == 8: return False
    t = sum(nums)
    if t < 99 or t > 189: return False
    lds = sum(n%10 for n in nums)
    if lds < 16 or lds > 39 or lds == 32: return False
    tc = {}
    for n in nums: tc[n%10] = tc.get(n%10, 0) + 1
    for d,(mn,mx) in TAIL_S.items():
        if not (mn<=tc.get(d,0)<=mx): return False
    odd = sum(1 for n in nums if n%2==1)
    if f"{odd}:{6-odd}" not in {"4:2","3:3","5:1","2:4"}: return False
    low = sum(1 for n in nums if n<=22)
    if f"{low}:{6-low}" not in {"2:4","4:2","3:3"}: return False
    if 17 in s: return False
    if sum(1 for n in nums if n in PRIMES)>3: return False
    if 36 in s: return False
    if sum(1 for n in nums if n in SQUARES)>1: return False
    if sum(1 for n in nums if n in TRIANGULARS)>2: return False
    if 44 in s: return False
    if sum(1 for n in nums if n in TWINS)>1: return False
    if sum(1 for n in nums if n in COMPOSITES) not in {3,4,5,6}: return False
    consec = sum(1 for i in range(5) if nums[i+1]-nums[i]==1)
    if consec > 1: return False
    if any(nums[i+1]-nums[i]==1 and nums[i+2]-nums[i+1]==1 for i in range(4)): return False
    r1=sum(1 for n in nums if 1<=n<=10); r2=sum(1 for n in nums if 11<=n<=20)
    r3=sum(1 for n in nums if 21<=n<=30); r4=sum(1 for n in nums if 31<=n<=40); r5=sum(1 for n in nums if 41<=n<=45)
    if not (0<=r1<=3 and 1<=r2<=2 and 0<=r3<=3 and 0<=r4<=3 and 0<=r5<=2): return False
    all_grp = {**GARO, **SERO}
    for p,(mn,mx) in PALACE_S.items():
        c = sum(1 for n in nums if n in PALACE[p])
        if not (mn<=c<=mx): return False
    for g,(mn,mx) in PAPER_S.items():
        c = sum(1 for n in nums if n in all_grp[g])
        if not (mn<=c<=mx): return False
    for m,(mn,mx) in MULT_S.items():
        c = sum(1 for n in nums if n in MULTIPLES.get(m,set()))
        if not (mn<=c<=mx): return False
    h = entropy_val(nums)
    if not (1.0<=h<=2.25): return False
    carry = sum(1 for n in nums if n in carryover_nums)
    if carry not in {0,1,2}: return False
    if sum(1 for n in nums if n in neighbors)>3: return False
    # hot/cold
    h5c=sum(1 for n in nums if n in hot5); c5c=sum(1 for n in nums if n in cold5); u5c=sum(1 for n in nums if n in neutral5)
    if not (HOT5_S['hotMin']<=h5c<=HOT5_S['hotMax'] and HOT5_S['coldMin']<=c5c<=HOT5_S['coldMax'] and HOT5_S['neutralMin']<=u5c<=HOT5_S['neutralMax']): return False
    h10c=sum(1 for n in nums if n in hot10); c10c=sum(1 for n in nums if n in cold10); u10c=sum(1 for n in nums if n in neutral10)
    if not (HOT10_S['hotMin']<=h10c<=HOT10_S['hotMax'] and HOT10_S['coldMin']<=c10c<=HOT10_S['coldMax'] and HOT10_S['neutralMin']<=u10c<=HOT10_S['neutralMax']): return False
    h15c=sum(1 for n in nums if n in hot15); c15c=sum(1 for n in nums if n in cold15); u15c=sum(1 for n in nums if n in neutral15)
    if not (HOT15_S['hotMin']<=h15c<=HOT15_S['hotMax'] and HOT15_S['coldMin']<=c15c<=HOT15_S['coldMax'] and HOT15_S['neutralMin']<=u15c<=HOT15_S['neutralMax']): return False
    h20c=sum(1 for n in nums if n in hot20); c20c=sum(1 for n in nums if n in cold20); u20c=sum(1 for n in nums if n in neutral20)
    if not (HOT20_S['hotMin']<=h20c<=HOT20_S['hotMax'] and HOT20_S['coldMin']<=c20c<=HOT20_S['coldMax'] and HOT20_S['neutralMin']<=u20c<=HOT20_S['neutralMax']): return False
    mg1=sum(1 for n in nums if n in miss_g1); mg2=sum(1 for n in nums if n in miss_g2)
    mg3=sum(1 for n in nums if n in miss_g3); mg4=sum(1 for n in nums if n in miss_g4)
    if not (MISS_S['r1']['min']<=mg1<=MISS_S['r1']['max'] and MISS_S['r2']['min']<=mg2<=MISS_S['r2']['max'] and MISS_S['r3']['min']<=mg3<=MISS_S['r3']['max'] and MISS_S['r4']['min']<=mg4<=MISS_S['r4']['max']): return False
    cg1=sum(1 for n in nums if n in CUST1); cg2=sum(1 for n in nums if n in CUST2)
    if not (2<=cg1<=6 and 1<=cg2<=3): return False
    return True

print("\n🔍 10개 생존 조합 찾는 중...")
survivors = []
for combo in combinations(range(1, 46), 6):
    if passes_foundation(list(combo)):
        survivors.append(list(combo))
        if len(survivors) >= 10:
            print(f"  10개 찾음!")
            break
    elif len(survivors) > 0 and len(survivors) < 10:
        pass

# But we need ALL 10, not stop at first 10
# Re-run to collect exactly 10
survivors = []
for combo in combinations(range(1, 46), 6):
    if passes_foundation(list(combo)):
        survivors.append(list(combo))

print(f"\n커스텀분석 전 총 통과: {len(survivors)}개")
print("\n각 조합별 커스텀 필터 실패 분석:")
for nums in survivors[:10]:
    print(f"\n조합: {nums}")
    all_ok = True
    for cname, ctargets, cmn, cmx in CUSTOM_FILTERS:
        cnt = sum(1 for n in nums if n in ctargets)
        ok = cmn <= cnt <= cmx
        status = "✅" if ok else "❌"
        if not ok:
            print(f"  {status} {cname}: {cnt}개 (허용:{cmn}-{cmx})")
            all_ok = False
    if all_ok:
        print(f"  ✅ 모든 커스텀 필터 통과!")
