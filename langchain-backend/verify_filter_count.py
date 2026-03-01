"""
verify_filter_count.py
사용자 설정 필터 24개를 전부 구현하여 8,145,060개 전수조사
타겟 회차: 1212 (필터 설정 기준)
"""
from itertools import combinations
from supabase import create_client
import math

SUPABASE_URL = 'https://dkcflmyoscudawleglzb.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo'

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── 회차 데이터 로드 (target=1212 기준: 1211 이하 데이터 사용) ──────────
print("📦 Supabase에서 회차 데이터 로딩...")
res = sb.table('lotto_draws').select('round,numbers,bonus').order('round', desc=True).limit(220).execute()
all_draws_raw = res.data  # 최신순 정렬

# target_round=1212 기준으로, 그 이전 데이터만 사용
# filter_dashboard.js의 allDraws는 당시 target 이전 회차들
# step2 → allDraws[1], step3 → allDraws[2], ...
# 당시 1212가 타겟이었으므로 allDraws[0]=1211, allDraws[1]=1210...
TARGET_ROUND = 1212
prev_draws = [d for d in all_draws_raw if d['round'] < TARGET_ROUND]
prev_draws.sort(key=lambda x: x['round'], reverse=True)  # 최신순

print(f"✅ 이전 회차 {len(prev_draws)}개 로드 (최신: {prev_draws[0]['round']})")
prev_round = prev_draws[0]  # 1211 (1212 이전 마지막)
carryover_nums = set(prev_round['numbers'])  # 1211회 번호
carryover_bonus = prev_round.get('bonus', 0)

# ── 정적 집합 정의 ──────────────────────────────────────────────────────
PRIMES       = {2,3,5,7,11,13,17,19,23,29,31,37,41,43}
SQUARES      = {1,4,9,16,25,36}
TRIANGULARS  = {1,3,6,10,15,21,28,36,45}
TWINS        = {11,22,33,44}
COMPOSITES   = {4,6,8,9,10,12,14,15,16,18,20,21,22,24,25,26,27,28,30,32,33,34,35,36,38,39,40,42,44,45}

GARO = {
    '가로1':{1,2,3,4,5,6,7},   '가로2':{8,9,10,11,12,13,14},
    '가로3':{15,16,17,18,19,20,21}, '가로4':{22,23,24,25,26,27,28},
    '가로5':{29,30,31,32,33,34,35}, '가로6':{36,37,38,39,40,41,42},
    '가로7':{43,44,45}
}
SERO = {
    '세로1':{1,8,15,22,29,36,43}, '세로2':{2,9,16,23,30,37,44},
    '세로3':{3,10,17,24,31,38,45}, '세로4':{4,11,18,25,32,39},
    '세로5':{5,12,19,26,33,40},   '세로6':{6,13,20,27,34,41},
    '세로7':{7,14,21,28,35,42}
}
PALACE = {
    '1궁':{1,2,3,4,5},  '2궁':{6,7,8,9,10},    '3궁':{11,12,13,14,15},
    '4궁':{16,17,18,19,20}, '5궁':{21,22,23,24,25}, '6궁':{26,27,28,29,30},
    '7궁':{31,32,33,34,35}, '8궁':{36,37,38,39,40}, '9궁':{41,42,43,44,45}
}
MULTIPLES = {
    '3배수':{3,6,9,12,15,18,21,24,27,30,33,36,39,42,45},
    '4배수':{4,8,12,16,20,24,28,32,36,40,44},
    '5배수':{5,10,15,20,25,30,35,40,45},
    '3·4배수':{12,24,36}, '3·5배수':{15,30,45}, '4·5배수':{20,40},
    '배수외':{1,2,7,11,13,14,17,19,22,23,26,29,31,34,37,38,41,43}
}

# ── hot/cold 분류 (5/10/15/20회 기준) ──────────────────────────────────
def get_hot_cold(draws_n):
    freq = {n: 0 for n in range(1, 46)}
    for d in draws_n:
        for n in d['numbers']: freq[n] += 1
    sorted_nums = sorted(freq.keys(), key=lambda x: freq[x], reverse=True)
    top15 = set(sorted_nums[:15])
    bot15 = set(sorted_nums[30:])
    hot, cold, neutral = set(), set(), set()
    for n in range(1, 46):
        if n in top15: hot.add(n)
        elif n in bot15: cold.add(n)
        else: neutral.add(n)
    return hot, cold, neutral

draws5  = prev_draws[:5]
draws10 = prev_draws[:10]
draws15 = prev_draws[:15]
draws20 = prev_draws[:20]

hot5,cold5,neutral5 = get_hot_cold(draws5)
hot10,cold10,neutral10 = get_hot_cold(draws10)
hot15,cold15,neutral15 = get_hot_cold(draws15)
hot20,cold20,neutral20 = get_hot_cold(draws20)

# ── 미출현 기간 계산 ─────────────────────────────────────────────────────
def calc_missing(draws_list):
    miss = {}
    found = set()
    for i, d in enumerate(draws_list):
        for n in d['numbers']:
            if n not in found:
                miss[n] = i + 1
                found.add(n)
    for n in range(1, 46):
        if n not in miss:
            miss[n] = len(draws_list) + 1
    return miss

miss_periods = calc_missing(prev_draws[:50])

# ── 이웃수 계산 ──────────────────────────────────────────────────────────
neighbors = set()
for n in carryover_nums:
    if n > 1: neighbors.add(n - 1)
    if n < 45: neighbors.add(n + 1)
neighbors -= carryover_nums

# ── 회귀 분석 데이터 준비 (step 2~200 → allDraws[1]~allDraws[199]) ──────
# filter_dashboard allDraws = prev_draws (1211, 1210, 1209...)
# step n → allDraws[n-1] = prev_draws[n-1]
regression_data = {}
for step in range(2, 201):
    idx = step - 1  # step2 → index1 = prev_draws[1] (1210회)
    if idx < len(prev_draws):
        regression_data[step] = set(prev_draws[idx]['numbers'])

print(f"✅ 이웃수: {sorted(neighbors)}")
print(f"✅ 이월수(1211회): {sorted(carryover_nums)}")
print(f"✅ 회귀 데이터: {len(regression_data)}회차")

# ── 필터 설정 (사용자 입력값 그대로) ────────────────────────────────────
FIXED = {5, 12}                 # hot_cold 전 기간 fixedNumbers
EXCLUDED = {2,17,27,31,34,36,37,38,44}  # hot_cold excludeNumbers + 개별 필터 제외수

PAPER_S = {
    '가로1':{'min':0,'max':2}, '가로2':{'min':0,'max':1}, '가로3':{'min':1,'max':2},
    '가로4':{'min':0,'max':3}, '가로5':{'min':0,'max':2}, '가로6':{'min':0,'max':3},
    '가로7':{'min':0,'max':1}, '세로1':{'min':0,'max':1}, '세로2':{'min':0,'max':3},
    '세로3':{'min':1,'max':3}, '세로4':{'min':0,'max':2}, '세로5':{'min':0,'max':2},
    '세로6':{'min':1,'max':2}, '세로7':{'min':0,'max':1}
}
PALACE_S = {p: {'min':1 if p=='3궁' else 0, 'max':2} for p in PALACE}
RANGE_S = {'1_10':{'min':0,'max':3},'11_20':{'min':1,'max':2},'21_30':{'min':0,'max':3},'31_40':{'min':0,'max':3},'41_45':{'min':0,'max':2}}
MULT_S = {'3배수':{'min':1,'max':4},'4배수':{'min':1,'max':2},'5배수':{'min':1,'max':2},'배수외':{'min':2,'max':5},'3·4배수':{'min':0,'max':1},'3·5배수':{'min':0,'max':1},'4·5배수':{'min':0,'max':1}}
TAIL_S = {0:(0,1),1:(0,3),2:(0,1),3:(0,1),4:(0,1),5:(0,2),6:(0,2),7:(0,3),8:(0,2),9:(0,1)}
HOT5_S  = {'hotMin':0,'hotMax':1,'coldMin':1,'coldMax':6,'neutralMin':0,'neutralMax':4}
HOT10_S = {'hotMin':0,'hotMax':3,'coldMin':0,'coldMax':3,'neutralMin':3,'neutralMax':6}
HOT15_S = {'hotMin':0,'hotMax':2,'coldMin':0,'coldMax':4,'neutralMin':1,'neutralMax':5}
HOT20_S = {'hotMin':0,'hotMax':2,'coldMin':0,'coldMax':3,'neutralMin':3,'neutralMax':6}
MISS_S  = {'r1':{'min':2,'max':6},'r2':{'min':1,'max':3},'r3':{'min':0,'max':1},'r4':{'min':1,'max':2}}
CUST1   = {1,2,3,4,5,6,7,8,9,10,16,17,18,20,22,23,24,25,26,27,28,29,30,31,35,36,37,38,39,40,41,42,44,45}
CUST2   = {11,12,13,14,15,19,21,32,33,34,43}

# 회귀 설정 (step: {min, max})
REGR = {2:{'min':0,'max':2},3:{'min':0,'max':2},4:{'min':0,'max':2},5:{'min':0,'max':2},
6:{'min':0,'max':2},7:{'min':0,'max':2},8:{'min':0,'max':1},9:{'min':0,'max':2},
10:{'min':0,'max':2},11:{'min':0,'max':2},12:{'min':0,'max':2},13:{'min':0,'max':3},
14:{'min':0,'max':3},15:{'min':0,'max':2},16:{'min':0,'max':2},17:{'min':0,'max':3},
18:{'min':0,'max':2},19:{'min':0,'max':2},20:{'min':0,'max':2},21:{'min':0,'max':3},
22:{'min':0,'max':2},23:{'min':0,'max':1},24:{'min':0,'max':2},25:{'min':0,'max':3},
26:{'min':0,'max':3},27:{'min':0,'max':2},28:{'min':0,'max':2},29:{'min':1,'max':2},
30:{'min':0,'max':2},31:{'min':0,'max':1},32:{'min':0,'max':2},33:{'min':0,'max':3},
34:{'min':0,'max':3},35:{'min':0,'max':3},36:{'min':0,'max':3},37:{'min':0,'max':2},
38:{'min':0,'max':2},39:{'min':0,'max':2},40:{'min':0,'max':3},41:{'min':0,'max':1},
42:{'min':0,'max':2},43:{'min':0,'max':2},44:{'min':0,'max':1},45:{'min':0,'max':2},
46:{'min':0,'max':3},47:{'min':0,'max':2},48:{'min':0,'max':2},49:{'min':0,'max':1},
50:{'min':0,'max':2},51:{'min':0,'max':3},52:{'min':0,'max':3},53:{'min':0,'max':3},
54:{'min':0,'max':2},55:{'min':0,'max':2},56:{'min':0,'max':2},57:{'min':0,'max':2},
58:{'min':0,'max':2},59:{'min':0,'max':2},60:{'min':0,'max':2},61:{'min':0,'max':3},
62:{'min':0,'max':2},63:{'min':0,'max':2},64:{'min':0,'max':3},65:{'min':0,'max':3},
66:{'min':0,'max':2},67:{'min':0,'max':2},68:{'min':0,'max':3},69:{'min':0,'max':2},
70:{'min':0,'max':3},71:{'min':0,'max':3},72:{'min':0,'max':2},73:{'min':0,'max':2},
74:{'min':0,'max':1},75:{'min':0,'max':2},76:{'min':0,'max':2},77:{'min':0,'max':2},
78:{'min':0,'max':2},79:{'min':0,'max':3},80:{'min':0,'max':2},81:{'min':0,'max':2},
82:{'min':0,'max':2},83:{'min':0,'max':2},84:{'min':0,'max':2},85:{'min':0,'max':1},
86:{'min':0,'max':2},87:{'min':0,'max':2},88:{'min':0,'max':2},89:{'min':0,'max':2},
90:{'min':0,'max':3},91:{'min':0,'max':2},92:{'min':0,'max':2},93:{'min':0,'max':3},
94:{'min':0,'max':2},95:{'min':0,'max':2},96:{'min':0,'max':2},97:{'min':0,'max':3},
98:{'min':0,'max':3},99:{'min':0,'max':2},100:{'min':0,'max':2},101:{'min':0,'max':2},
102:{'min':0,'max':3},103:{'min':0,'max':2},104:{'min':0,'max':2},105:{'min':0,'max':2},
106:{'min':0,'max':2},107:{'min':0,'max':3},108:{'min':0,'max':4},109:{'min':0,'max':2},
110:{'min':0,'max':2},111:{'min':0,'max':2},112:{'min':0,'max':2},113:{'min':0,'max':2},
114:{'min':0,'max':2},115:{'min':0,'max':2},116:{'min':0,'max':3},117:{'min':0,'max':3},
118:{'min':0,'max':1},119:{'min':0,'max':2},120:{'min':0,'max':2},121:{'min':0,'max':2},
122:{'min':0,'max':2},123:{'min':0,'max':1},124:{'min':0,'max':1},125:{'min':0,'max':2},
126:{'min':0,'max':3},127:{'min':0,'max':2},128:{'min':0,'max':2},129:{'min':0,'max':3},
130:{'min':0,'max':2},131:{'min':0,'max':2},132:{'min':0,'max':2},133:{'min':0,'max':1},
134:{'min':0,'max':1},135:{'min':0,'max':2},136:{'min':0,'max':2},137:{'min':0,'max':2},
138:{'min':0,'max':1},139:{'min':0,'max':3},140:{'min':0,'max':2},141:{'min':0,'max':2},
142:{'min':0,'max':2},143:{'min':0,'max':2},144:{'min':0,'max':2},145:{'min':0,'max':2},
146:{'min':0,'max':3},147:{'min':0,'max':2},148:{'min':0,'max':2},149:{'min':0,'max':2},
150:{'min':0,'max':2},151:{'min':0,'max':2},152:{'min':1,'max':2},153:{'min':0,'max':2},
154:{'min':0,'max':3},155:{'min':0,'max':2},156:{'min':0,'max':1},157:{'min':0,'max':1},
158:{'min':0,'max':3},159:{'min':0,'max':1},160:{'min':0,'max':2},161:{'min':0,'max':2},
162:{'min':0,'max':2},163:{'min':0,'max':2},164:{'min':1,'max':2},165:{'min':0,'max':2},
166:{'min':1,'max':1},167:{'min':0,'max':1},168:{'min':0,'max':2},169:{'min':0,'max':2},
170:{'min':1,'max':3},171:{'min':0,'max':1},172:{'min':0,'max':2},173:{'min':0,'max':1},
174:{'min':0,'max':3},175:{'min':0,'max':2},176:{'min':0,'max':2},177:{'min':0,'max':2},
178:{'min':0,'max':2},179:{'min':0,'max':2},180:{'min':0,'max':1},181:{'min':0,'max':2},
182:{'min':0,'max':2},183:{'min':0,'max':2},184:{'min':0,'max':2},185:{'min':0,'max':2},
186:{'min':1,'max':2},187:{'min':0,'max':2},188:{'min':0,'max':2},189:{'min':0,'max':3},
190:{'min':0,'max':3},191:{'min':0,'max':2},192:{'min':0,'max':1},193:{'min':0,'max':2},
194:{'min':0,'max':1},195:{'min':0,'max':1},196:{'min':0,'max':2},197:{'min':0,'max':1},
198:{'min':0,'max':2},199:{'min':0,'max':2},200:{'min':0,'max':2}}

# ── AC값 계산 ─────────────────────────────────────────────────────────────
def calc_ac(nums):
    diffs = set()
    s = sorted(nums)
    for i in range(len(s)):
        for j in range(i+1, len(s)):
            diffs.add(s[j] - s[i])
    return len(diffs) - (len(nums) - 1)

# ── 미출현 그룹 분류 ──────────────────────────────────────────────────────
miss_g1, miss_g2, miss_g3, miss_g4 = set(), set(), set(), set()
for n in range(1, 46):
    m = miss_periods.get(n, 999)
    if m <= 5:   miss_g1.add(n)
    elif m <= 10: miss_g2.add(n)
    elif m <= 15: miss_g3.add(n)
    else:         miss_g4.add(n)

print(f"\n미출현 그룹: G1(≤5)={sorted(miss_g1)} G2(6-10)={sorted(miss_g2)}")
print(f"           G3(11-15)={sorted(miss_g3)} G4(16+)={sorted(miss_g4)}\n")
print("🔍 전수조사 시작...")

# ── 전수조사 ──────────────────────────────────────────────────────────────
count = 0
valid_combos = []
TOTAL = 8145060
checked = 0

for combo in combinations(range(1, 46), 6):
    checked += 1
    if checked % 500000 == 0:
        print(f"  {checked:,} / {TOTAL:,} 검사 중... (현재 통과: {count}개)")

    s = set(combo)
    nums = list(combo)

    # 1. 고정수 포함 필수
    if not FIXED.issubset(s): continue

    # 2. 제외수 없어야
    if s & EXCLUDED: continue

    # 3. AC값 (7 또는 9, 8 제외)
    ac = calc_ac(nums)
    if ac < 7 or ac > 9 or ac == 8: continue

    # 4. 총합 99-189
    total = sum(nums)
    if total < 99 or total > 189: continue

    # 5. 끝수합 16-39, 32 제외
    lds = sum(n % 10 for n in nums)
    if lds < 16 or lds > 39 or lds == 32: continue

    # 6. 끝수별 개수
    ok = True
    tc = {}
    for n in nums: tc[n%10] = tc.get(n%10,0)+1
    for d,(mn,mx) in TAIL_S.items():
        if not (mn <= tc.get(d,0) <= mx): ok=False; break
    if not ok: continue

    # 7. 홀짝 [4:2, 3:3, 5:1, 2:4]
    odd = sum(1 for n in nums if n%2==1)
    if f"{odd}:{6-odd}" not in {"4:2","3:3","5:1","2:4"}: continue

    # 8. 고저 [2:4, 4:2, 3:3] (저≤22)
    low = sum(1 for n in nums if n<=22)
    if f"{low}:{6-low}" not in {"2:4","4:2","3:3"}: continue

    # 9. 소수 개수 [0,1,2,3] (17 제외됨)
    pc = sum(1 for n in nums if n in PRIMES)
    if pc > 3: continue

    # 10. 제곱수 개수 [0,1] (36 제외됨)
    sc = sum(1 for n in nums if n in SQUARES)
    if sc > 1: continue

    # 11. 삼각수 개수 [0,1,2]
    tc2 = sum(1 for n in nums if n in TRIANGULARS)
    if tc2 > 2: continue

    # 12. 쌍수 개수 [0,1] (44 제외됨)
    tw = sum(1 for n in nums if n in TWINS)
    if tw > 1: continue

    # 13. 합성수 개수 [3,4,5,6] (27,38 제외됨)
    cc = sum(1 for n in nums if n in COMPOSITES)
    if cc not in {3,4,5,6}: continue

    # 14. 연속번호 [0,1], 3연속 금지
    consec = sum(1 for i in range(5) if nums[i+1]-nums[i]==1)
    if consec > 1: continue
    has3 = any(nums[i+1]-nums[i]==1 and nums[i+2]-nums[i+1]==1 for i in range(4))
    if has3: continue

    # 15. 번호대 (1-10:0-3, 11-20:1-2, 21-30:0-3, 31-40:0-3, 41-45:0-2)
    r1=sum(1 for n in nums if 1<=n<=10)
    r2=sum(1 for n in nums if 11<=n<=20)
    r3=sum(1 for n in nums if 21<=n<=30)
    r4=sum(1 for n in nums if 31<=n<=40)
    r5=sum(1 for n in nums if 41<=n<=45)
    if not (0<=r1<=3 and 1<=r2<=2 and 0<=r3<=3 and 0<=r4<=3 and 0<=r5<=2): continue

    # 16. 9궁 (3궁 min:1, 나머지 min:0, 전부 max:2)
    ok = True
    for p,ps in PALACE_S.items():
        c = sum(1 for n in nums if n in PALACE[p])
        if not (ps['min']<=c<=ps['max']): ok=False; break
    if not ok: continue

    # 17. 용지패턴 (가로/세로)
    ok = True
    all_groups = {**GARO, **SERO}
    for g,ps in PAPER_S.items():
        c = sum(1 for n in nums if n in all_groups[g])
        if not (ps['min']<=c<=ps['max']): ok=False; break
    if not ok: continue

    # 18. 배수패턴
    ok = True
    for m,ms in MULT_S.items():
        c = sum(1 for n in nums if n in MULTIPLES[m])
        if not (ms['min']<=c<=ms['max']): ok=False; break
    if not ok: continue

    # 19. 이월수 (1211회 번호 [0,1,2]개 포함)
    carry = sum(1 for n in nums if n in carryover_nums)
    if carry not in {0,1,2}: continue

    # 20. 이웃수 0-3개
    nb = sum(1 for n in nums if n in neighbors)
    if nb > 3: continue

    # 21. hot/cold 5회 (hotMax:1,coldMin:1,coldMax:6,neutralMax:4)
    h5=sum(1 for n in nums if n in hot5)
    c5=sum(1 for n in nums if n in cold5)
    u5=sum(1 for n in nums if n in neutral5)
    if not (HOT5_S['hotMin']<=h5<=HOT5_S['hotMax'] and
            HOT5_S['coldMin']<=c5<=HOT5_S['coldMax'] and
            HOT5_S['neutralMin']<=u5<=HOT5_S['neutralMax']): continue

    # 22. hot/cold 10회
    h10=sum(1 for n in nums if n in hot10)
    c10=sum(1 for n in nums if n in cold10)
    u10=sum(1 for n in nums if n in neutral10)
    if not (HOT10_S['hotMin']<=h10<=HOT10_S['hotMax'] and
            HOT10_S['coldMin']<=c10<=HOT10_S['coldMax'] and
            HOT10_S['neutralMin']<=u10<=HOT10_S['neutralMax']): continue

    # 23. hot/cold 15회
    h15=sum(1 for n in nums if n in hot15)
    c15=sum(1 for n in nums if n in cold15)
    u15=sum(1 for n in nums if n in neutral15)
    if not (HOT15_S['hotMin']<=h15<=HOT15_S['hotMax'] and
            HOT15_S['coldMin']<=c15<=HOT15_S['coldMax'] and
            HOT15_S['neutralMin']<=u15<=HOT15_S['neutralMax']): continue

    # 24. hot/cold 20회
    h20=sum(1 for n in nums if n in hot20)
    c20=sum(1 for n in nums if n in cold20)
    u20=sum(1 for n in nums if n in neutral20)
    if not (HOT20_S['hotMin']<=h20<=HOT20_S['hotMax'] and
            HOT20_S['coldMin']<=c20<=HOT20_S['coldMax'] and
            HOT20_S['neutralMin']<=u20<=HOT20_S['neutralMax']): continue

    # 25. 미출현 기간 그룹별 범위
    mg1=sum(1 for n in nums if n in miss_g1)
    mg2=sum(1 for n in nums if n in miss_g2)
    mg3=sum(1 for n in nums if n in miss_g3)
    mg4=sum(1 for n in nums if n in miss_g4)
    if not (MISS_S['r1']['min']<=mg1<=MISS_S['r1']['max'] and
            MISS_S['r2']['min']<=mg2<=MISS_S['r2']['max'] and
            MISS_S['r3']['min']<=mg3<=MISS_S['r3']['max'] and
            MISS_S['r4']['min']<=mg4<=MISS_S['r4']['max']): continue

    # 26. 미출현 커스텀 그룹
    cg1=sum(1 for n in nums if n in CUST1)
    cg2=sum(1 for n in nums if n in CUST2)
    if not (2<=cg1<=6 and 1<=cg2<=3): continue

    # 27. 회귀 분석 (step 2~200)
    ok = True
    for step, rset in regression_data.items():
        if step not in REGR: continue
        rs = REGR[step]
        overlap = sum(1 for n in nums if n in rset)
        if not (rs['min']<=overlap<=rs['max']): ok=False; break
    if not ok: continue

    count += 1
    valid_combos.append(nums)

print(f"\n{'='*50}")
print(f"✅ 전수조사 완료! 통과 조합: {count}개")
print(f"{'='*50}")
if valid_combos:
    for i, c in enumerate(valid_combos):
        print(f"  조합 {i+1}: {c}")
