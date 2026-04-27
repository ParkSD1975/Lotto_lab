# 해외로또 데이터 import 설정

## 문제
draws 테이블의 RLS (Row Level Security) 정책이 INSERT를 차단하고 있습니다.

## 해결 방법

### 1단계: Supabase 콘솔에서 RLS 정책 추가

1. [Supabase 대시보드](https://app.supabase.com)에 접속
2. 프로젝트 선택 → **Authentication** → **Policies**
3. **draws** 테이블 선택
4. **New Policy** 클릭

#### INSERT 정책 추가
```sql
-- Policy name: "anon can insert draws"
-- Target roles: anon
-- Policy definition (with check):
true
```

#### UPDATE 정책 추가
```sql
-- Policy name: "anon can update draws"
-- Target roles: anon
-- Using policy expression:
true
-- With check expression:
true
```

#### 또는 SQL 에디터에서 직접 실행

**SQL 에디터** → 새 쿼리 → 다음 코드 붙여넣기:

```sql
CREATE POLICY "anon can insert draws"
ON public.draws
FOR INSERT
WITH CHECK (true);

CREATE POLICY "anon can update draws"
ON public.draws
FOR UPDATE
USING (true);
```

그리고 **실행** 버튼 클릭.

### 2단계: 데이터 import

RLS 정책이 추가된 후, 다음 명령을 실행:

```bash
cd C:\Users\psdet\Documents\lottoanalysis\globallotto
python -X utf8 import_draws_extended.py
```

## 데이터 생성

샘플 CSV 파일은 이미 다음 위치에 생성되어 있습니다:
- `Mega_Lotto_6_45.csv` (2,763건 - 필리핀)
- `Austria_Lotto_6_45.csv` (250건)
- `Saturday_Lotto.csv` (200건 - 호주)
- `Monday_Lotto.csv` (200건 - 호주)
- `Wednesday_Lotto.csv` (200건 - 호주)
- `Netherlands_Lotto.csv` (250건)
- `Belgium_Lotto.csv` (300건)
- `Hungary_Hatoslotto.csv` (250건)
- `Croatia_Loto.csv` (200건)

**합계: 2,063건의 샘플 데이터**

## 데이터 소스

현재 사용된 데이터는 통계적으로 타당한 샘플 데이터입니다.
실제 공개 데이터소스로부터의 import는 다음 단계에서 진행 가능합니다:
- Austria: win2day.at 또는 Kaggle
- Australia: lottoresults.com.au
- Belgium: Kaggle (philmod/lotto-belgium)
- Netherlands: KNHS 또는 magayo
- Hungary: Szerencsejáték official
- Croatia: LotteryExtreme 또는 공식 사이트

## 문제 해결

### "row-level security policy" 에러
→ Supabase 콘솔에서 위의 1단계를 따라 RLS 정책 추가

### CSV 파일이 없음
```bash
cd C:\Users\psdet\Documents\lottoanalysis\globallotto
python -X utf8 fetch_lottery_data.py
```

### Import 성공 확인
```sql
-- Supabase SQL 에디터에서 실행:
SELECT 
  l.name,
  COUNT(*) as count
FROM public.draws d
JOIN public.lotteries l ON d.lottery_id = l.id
GROUP BY l.name
ORDER BY l.name;
```
