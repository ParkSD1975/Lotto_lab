# 🚀 Supabase CSV 직접 Import 가이드 (가장 빠른 방법!)

## ⚠️ 현재 상황
Python 스크립트로 업로드 시 Supabase 테이블 구조와 맞지 않는 문제가 발생하고 있습니다.

**가장 빠른 해결책: Supabase 대시보드에서 직접 CSV Import! (3분 소요)**

---

## 📋 단계별 가이드

### 1️⃣ Supabase 대시보드 접속

1. https://supabase.com 로그인
2. 프로젝트 선택: `dkcflmyoscudawleglzb`

---

### 2️⃣ 테이블 생성 (이미 있다면 Skip)

1. 좌측 메뉴 **Table Editor** 클릭
2. **New table** 버튼 클릭
3. 테이블 이름: `lotto_draws`
4. **Import data from spreadsheet** 클릭

---

### 3️⃣ CSV 파일 업로드

1. **Select CSV file** 버튼 클릭
2. `lotto.csv` 파일 선택
3. **Preview** 확인:
   - `round` → integer
   - `date` → date
   - `numbers` → text (일단 텍스트로 import)
   - `bonus` → integer
   - `sum` → integer

4. **Save** 버튼 클릭

---

### 4️⃣ numbers 컬럼 타입 변경

CSV import 후 `numbers` 컬럼을 배열로 변경해야 합니다.

1. 좌측 메뉴 **SQL Editor** 클릭
2. 다음 SQL 실행:

```sql
-- 1. numbers 컬럼의 데이터 형식 확인
SELECT round, numbers FROM lotto_draws LIMIT 5;

-- 2. 임시 컬럼 생성
ALTER TABLE lotto_draws ADD COLUMN numbers_array integer[];

-- 3. 텍스트 → 배열 변환
UPDATE lotto_draws 
SET numbers_array = string_to_array(
    trim(both '{}' from numbers), 
    ','
)::integer[];

-- 4. 기존 컬럼 삭제 후 이름 변경
ALTER TABLE lotto_draws DROP COLUMN numbers;
ALTER TABLE lotto_draws RENAME COLUMN numbers_array TO numbers;

-- 5. 확인
SELECT round, date, numbers, bonus FROM lotto_draws LIMIT 10;
```

---

### 5️⃣ 인덱스 및 제약 조건 추가 (선택사항)

```sql
-- Primary Key 설정
ALTER TABLE lotto_draws ADD PRIMARY KEY (round);

-- 인덱스 생성 (빠른 검색)
CREATE INDEX idx_lotto_draws_date ON lotto_draws(date DESC);
CREATE INDEX idx_lotto_draws_round ON lotto_draws(round DESC);

-- RLS (Row Level Security) 활성화
ALTER TABLE lotto_draws ENABLE ROW LEVEL SECURITY;

-- 모든 사용자가 읽을 수 있도록
CREATE POLICY "Allow public read" ON lotto_draws
    FOR SELECT USING (true);
```

---

## ✅ 완료 확인

1. **Table Editor**에서 `lotto_draws` 테이블 확인
2. 총 1,203개 행이 있는지 확인
3. `numbers` 컬럼이 배열 형식인지 확인

---

## 🎯 다음 단계

CSV import가 완료되면:

1. **Streamlit 앱 실행:**
```powershell
streamlit run app.py
```

2. **브라우저에서 확인:**
   - http://localhost:8501
   - 데이터가 정상적으로 표시되어야 함

3. **당첨번호 페이지 확인:**
   - `기초분석_통합/winning-numbers.html` 열기
   - 데이터가 로드되는지 확인

---

## 🆘 문제 발생 시

### 문제: CSV import가 안 됨
**해결:** CSV 파일 인코딩을 UTF-8로 변경
```powershell
Get-Content lotto.csv | Out-File -Encoding UTF8 lotto_utf8.csv
```

### 문제: numbers 컬럼 변환 오류
**해결:** 수동으로 데이터 확인
```sql
-- 변환 전 데이터 형식 확인
SELECT numbers FROM lotto_draws LIMIT 1;
-- 예상 형식: "{3,6,18,29,35,39}"
```

### 문제: 데이터가 표시되지 않음
**해결:** 브라우저 개발자 도구 (F12) → Console 탭에서 오류 확인

---

## 💡 왜 이 방법이 가장 빠른가요?

✅ **장점:**
- Supabase가 자동으로 데이터 타입 감지
- 1,203개 행을 한 번에 업로드
- Python 스크립트 오류 걱정 없음
- 약 3-5분이면 완료

❌ **Python 스크립트의 문제:**
- 테이블 구조를 정확히 알아야 함
- 네트워크 연결 필요
- 각 행마다 API 호출 (느림)
- 오류 발생 시 디버깅 어려움

---

## 🎉 축하합니다!

이제 로또 분석 시스템이 완전히 작동합니다! 🚀