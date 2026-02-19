# 🎰 동행복권 로또 API ↔ Supabase 연동 가이드

## 📋 목차
1. [Supabase 테이블 생성](#1-supabase-테이블-생성)
2. [Python 스크립트로 동기화](#2-python-스크립트로-동기화-추천)
3. [Supabase Edge Function으로 동기화](#3-supabase-edge-function으로-동기화)
4. [프론트엔드에서 최신 데이터 요청](#4-프론트엔드에서-최신-데이터-요청)

---

## 1. Supabase 테이블 생성

### 1-1. Supabase 대시보드 접속
1. https://supabase.com 로그인
2. 프로젝트 선택
3. 좌측 메뉴 **SQL Editor** 클릭

### 1-2. 테이블 생성 SQL 실행
`supabase/schema.sql` 파일의 내용을 복사해서 실행하세요.

```sql
-- SQL Editor에 붙여넣고 Run 버튼 클릭
```

### 1-3. 테이블 확인
- 좌측 메뉴 **Table Editor** → `lotto_draws` 테이블이 생성되었는지 확인

---

## 2. Python 스크립트로 동기화 (추천)

### 2-1. 필수 라이브러리 설치
```bash
pip install supabase requests
```

### 2-2. 스크립트 실행 방법

#### ✅ **최신 회차만 동기화**
```bash
python sync_lotto_data.py --latest
```

#### ✅ **최근 10개 회차 동기화**
```bash
python sync_lotto_data.py
```

#### ✅ **전체 데이터 동기화** (1회차부터 최신까지)
```bash
python sync_lotto_data.py --all
```

#### ✅ **특정 범위 동기화**
```bash
python sync_lotto_data.py --start 1 --end 100
```

### 2-3. 실행 결과 예시
```
==================================================
🎰 로또 데이터 동기화 시작
==================================================
📊 범위: 1140회차 ~ 1150회차
⏰ 시작 시간: 2026-01-13 14:30:00
==================================================

[1140/1150] ✅ 회차 1140: 저장 완료
[1141/1150] ✅ 회차 1141: 저장 완료
[1142/1150] ✅ 회차 1142: 저장 완료
...

==================================================
✨ 동기화 완료!
==================================================
✅ 성공: 11건
❌ 실패: 0건
⏰ 종료 시간: 2026-01-13 14:31:15
==================================================
```

---

## 3. Supabase Edge Function으로 동기화

### 3-1. Edge Function 배포

```bash
# Supabase CLI 설치 (처음 한 번만)
npm install -g supabase

# 로그인
supabase login

# 프로젝트 연결
supabase link --project-ref [YOUR_PROJECT_REF]

# Edge Function 배포
supabase functions deploy sync-lotto-data
```

### 3-2. 환경 변수 설정

Supabase 대시보드에서:
1. **Settings** → **Edge Functions**
2. 환경 변수 추가:
   - `SUPABASE_URL`: 프로젝트 URL
   - `SUPABASE_SERVICE_ROLE_KEY`: 서비스 역할 키

### 3-3. Edge Function 호출 방법

#### JavaScript에서 호출:
```javascript
// 최신 회차만 동기화
const response = await fetch(
  'https://[YOUR_PROJECT_REF].supabase.co/functions/v1/sync-lotto-data',
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${SUPABASE_ANON_KEY}`
    },
    body: JSON.stringify({ mode: 'latest' })
  }
)

const result = await response.json()
console.log(result) // { success: true, results: {...}, latest_round: 1150 }
```

#### 모드 옵션:
- `{ mode: 'latest' }` - 최신 회차만
- `{ mode: 'recent' }` - 최근 10개
- `{ start: 1, end: 100 }` - 특정 범위

---

## 4. 프론트엔드에서 최신 데이터 요청

### 4-1. 기존 `winning-numbers.html` 업데이트 버튼 수정

`triggerUpdate()` 함수를 다음과 같이 수정:

```javascript
async function triggerUpdate() {
    const btn = document.getElementById('btnUpdate');
    const original = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined text-lg animate-spin">sync</span> 업데이트 중...';
    btn.disabled = true;

    try {
        // Edge Function 호출
        const response = await fetch(
            'https://dkcflmyoscudawleglzb.supabase.co/functions/v1/sync-lotto-data',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${SUPABASE_CONFIG.KEY}`
                },
                body: JSON.stringify({ mode: 'latest' })
            }
        );

        if (!response.ok) throw new Error('업데이트 실패');
        
        const data = await response.json();
        alert(`✅ 최신 데이터 업데이트 완료!\n최신 회차: ${data.latest_round}회`);
        initPage(); // 목록 새로고침
    } catch (err) {
        console.error('업데이트 실패:', err);
        alert('⚠️ 업데이트 실패\n수동으로 Python 스크립트를 실행해주세요.');
    } finally {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}
```

---

## 5. 자동화 설정 (선택사항)

### 5-1. Windows 작업 스케줄러로 자동 동기화

1. **작업 스케줄러** 실행
2. **기본 작업 만들기** 클릭
3. 설정:
   - 이름: "로또 데이터 자동 동기화"
   - 트리거: 매주 토요일 오후 9시
   - 작업: `python C:\Users\psdet\Desktop\디자인\sync_lotto_data.py --latest`

### 5-2. Supabase Cron Job (유료 플랜)

```sql
-- pg_cron으로 매주 토요일 21:00에 자동 실행
SELECT cron.schedule(
    'sync-lotto-weekly',
    '0 21 * * 6',
    $$
    SELECT net.http_post(
        url:='https://[YOUR_PROJECT_REF].supabase.co/functions/v1/sync-lotto-data',
        headers:='{"Content-Type": "application/json", "Authorization": "Bearer [SERVICE_KEY]"}'::jsonb,
        body:='{"mode": "latest"}'::jsonb
    ) as request_id;
    $$
);
```

---

## 6. 문제 해결

### ❌ "테이블을 찾을 수 없습니다" 오류
- Supabase에서 `schema.sql` 실행했는지 확인
- 테이블 이름이 `lotto_draws`인지 확인

### ❌ "API 응답 실패" 오류
- 동행복권 사이트가 점검 중일 수 있습니다
- 나중에 다시 시도하세요

### ❌ "Supabase 저장 실패" 오류
- Supabase 키가 올바른지 확인
- RLS 정책이 올바르게 설정되었는지 확인

---

## 7. 다음 단계

✅ 데이터 동기화 완료  
✅ 프론트엔드에서 데이터 조회 가능  
✅ 분석 페이지에서 통계 확인  

**축하합니다! 🎉**  
이제 로또 분석 시스템이 완전히 작동합니다!