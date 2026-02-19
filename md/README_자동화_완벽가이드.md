# 🎰 로또 데이터 자동 동기화 완벽 가이드

## 🎯 해결된 문제

**요구사항:** 프론트에서 버튼을 누르지 않아도 자동으로 주기적으로 동행복권에서 데이터를 가져와야 함

**해결 방법:** 서버에서 자동으로 주기적으로 실행되는 시스템 구축

---

## ⚡ 빠른 시작 (5분 완성)

```powershell
# 1. 필수 라이브러리 설치
pip install apscheduler tenacity

# 2. 개선된 스크립트 테스트
python sync_lotto_data_improved.py --update

# 3. Windows 작업 스케줄러 설정 (아래 가이드 참고)
```

---

## 📁 생성된 파일들

### 1. `sync_lotto_data_improved.py` ⭐
- 재시도 로직 포함 (최대 3회)
- 자동 지수 백오프 (Exponential Backoff)
- DB와 API 비교하여 신규 회차만 동기화
- 오류 처리 강화

**사용법:**
```powershell
# 신규 회차만 자동 감지 및 동기화
python sync_lotto_data_improved.py --update

# 최신 회차만
python sync_lotto_data_improved.py --latest

# 특정 범위
python sync_lotto_data_improved.py --start 1 --end 100
```

### 2. `auto_sync_scheduler.py`
- 매주 토요일 21:30 자동 실행
- 매주 일요일 09:00 확인 실행
- 로그 파일 자동 생성 (`lotto_sync.log`)

**사용법:**
```powershell
python auto_sync_scheduler.py
```

---

## 🔧 Windows 작업 스케줄러 설정 (추천)

### 방법 1: GUI로 설정 (초보자용)

1. `Win + R` → `taskschd.msc` 입력

2. **작업 만들기** (우측 패널) 클릭

3. **일반 탭**
   - 이름: `로또 데이터 자동 동기화`
   - 설명: `매주 토요일 밤 동행복권 최신 데이터 가져오기`
   - ✅ 가장 높은 권한으로 실행

4. **트리거 탭**
   - **새로 만들기** 클릭
   - 작업 시작: `일정`
   - 설정: `매주`
   - 요일: ✅ 토요일
   - 시간: `21:30`
   - ✅ 사용함

5. **동작 탭**
   - **새로 만들기** 클릭
   - 동작: `프로그램 시작`
   - 프로그램/스크립트:
     ```
     python.exe
     ```
   - 인수 추가:
     ```
     sync_lotto_data_improved.py --update
     ```
   - 시작 위치:
     ```
     C:\Users\psdet\Desktop\디자인
     ```

6. **조건 탭**
   - ❌ AC 전원 사용 시에만 작업 시작 (체크 해제)

7. **설정 탭**
   - ✅ 작업 실패 시 다시 시작 간격: `1분`
   - ✅ 다음 시간 후 작업 중지: `1시간`

8. **확인** 클릭

### 방법 2: PowerShell로 설정 (고급 사용자용)

```powershell
# 작업 동작 정의
$action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument "sync_lotto_data_improved.py --update" `
    -WorkingDirectory "C:\Users\psdet\Desktop\디자인"

# 트리거 정의 (매주 토요일 21:30)
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Saturday `
    -At 21:30

# 추가 트리거 (일요일 확인용)
$trigger2 = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Sunday `
    -At 09:00

# 설정
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# 작업 등록
Register-ScheduledTask `
    -TaskName "로또데이터자동동기화" `
    -Action $action `
    -Trigger $trigger,$trigger2 `
    -Settings $settings `
    -Description "동행복권 최신 데이터 자동 동기화" `
    -RunLevel Highest
```

### 확인 및 관리

```powershell
# 등록 확인
Get-ScheduledTask -TaskName "로또데이터자동동기화"

# 즉시 실행 (테스트)
Start-ScheduledTask -TaskName "로또데이터자동동기화"

# 마지막 실행 결과
Get-ScheduledTaskInfo -TaskName "로또데이터자동동기화" | 
    Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime

# 삭제 (필요시)
Unregister-ScheduledTask -TaskName "로또데이터자동동기화" -Confirm:$false
```

---

## 📊 동작 방식

### 1. 자동 감지 (`--update` 옵션)

```
1. Supabase에서 마지막 회차 확인 (예: 1150회)
2. 동행복권 API에서 최신 회차 확인 (예: 1153회)
3. 신규 회차만 동기화 (1151, 1152, 1153)
```

### 2. 재시도 로직 (Tenacity)

```
네트워크 오류 발생 시:
  └─ 1차 시도 실패
  └─ 2초 대기 후 2차 시도
  └─ 4초 대기 후 3차 시도
  └─ 최종 실패 → 로그 기록
```

### 3. 스케줄 실행

```
토요일 21:30 (추첨 직후)
  └─ sync_lotto_data_improved.py --update 실행
  └─ 신규 회차 자동 감지
  └─ Supabase에 저장
  └─ 로그 기록

일요일 09:00 (확인용)
  └─ 혹시 누락된 데이터 재확인
```

---

## 🔍 로그 확인

### Python 스케줄러 로그

```powershell
# 전체 로그
Get-Content lotto_sync.log

# 최근 50줄
Get-Content lotto_sync.log -Tail 50

# 실시간 모니터링
Get-Content lotto_sync.log -Wait
```

### Windows 작업 스케줄러 로그

```powershell
# 이벤트 뷰어 열기
eventvwr.msc

# 또는 PowerShell로 확인
Get-WinEvent -FilterHashtable @{
    LogName='Microsoft-Windows-TaskScheduler/Operational'
    TaskDisplayName='로또데이터자동동기화'
} -MaxEvents 10
```

---

## 🧪 테스트 방법

### 1단계: 수동 실행 테스트

```powershell
# 현재 상태 확인
python sync_lotto_data_improved.py --update
```

**예상 출력:**
```
🔍 최신 회차를 찾는 중...
✅ 최신 회차: 1153회 (DB 마지막: 1150회)

==================================================
🎰 로또 데이터 동기화 시작
==================================================
📊 범위: 1151회차 ~ 1153회차
⏰ 시작 시간: 2026-01-15 22:45:00
==================================================

[1151/1153] ✅ 회차 1151: 저장 완료
[1152/1153] ✅ 회차 1152: 저장 완료
[1153/1153] ✅ 회차 1153: 저장 완료

==================================================
✨ 동기화 완료!
==================================================
✅ 성공: 3건
❌ 실패: 0건
⏰ 종료 시간: 2026-01-15 22:45:15
==================================================
```

### 2단계: 작업 스케줄러 테스트

```powershell
# 작업 즉시 실행
Start-ScheduledTask -TaskName "로또데이터자동동기화"

# 5초 대기
Start-Sleep -Seconds 5

# 결과 확인
Get-ScheduledTaskInfo -TaskName "로또데이터자동동기화"
```

### 3단계: Streamlit 앱에서 확인

```powershell
streamlit run app.py
```

http://localhost:8501 접속하여 데이터 확인

---

## 🎯 권장 설정

| 환경 | 방법 | 이유 |
|------|------|------|
| 개인 PC | Windows 작업 스케줄러 | 안정적, 설치 불필요 |
| 개발 환경 | Python 스케줄러 | 로그 확인 편리 |
| 서버 | 백그라운드 서비스 (NSSM) | 24시간 실행 |

---

## 💡 FAQ

### Q: PC를 끄면 동기화가 안 되나요?
**A:** 네, Windows 작업 스케줄러는 PC가 켜져 있어야 합니다. 
- 해결책: PC를 절전 모드로 두거나, 클라우드 서버 사용

### Q: 동행복권 API가 응답하지 않으면?
**A:** 자동으로 3회까지 재시도합니다.
- 1차: 즉시
- 2차: 2초 후
- 3차: 4초 후
- 실패 시 로그에 기록

### Q: Supabase 용량 초과 걱정은?
**A:** 무료 플랜 기준:
- 로또 데이터: 회차당 약 0.5KB
- 1,200회차 = 약 600KB
- 무료 플랜 500MB이므로 여유 있음

### Q: 여러 회차를 한 번에 동기화하면?
**A:** API 부하 방지를 위해 각 회차마다 1초씩 대기합니다.
- 10회차 = 약 10초 소요

---

## 🚀 실전 배포 체크리스트

- [ ] 1. `pip install apscheduler tenacity` 실행
- [ ] 2. `python sync_lotto_data_improved.py --update` 테스트
- [ ] 3. Windows 작업 스케줄러 등록
- [ ] 4. 작업 즉시 실행 테스트
- [ ] 5. 로그 파일 확인
- [ ] 6. Streamlit 앱에서 데이터 확인
- [ ] 7. 다음 토요일 21:30 자동 실행 대기

---

## 🎉 완료!

이제 로또 데이터가 **완전 자동**으로 업데이트됩니다!

✅ 매주 토요일 21:30 자동 실행
✅ 신규 회차만 스마트하게 감지
✅ 네트워크 오류 시 자동 재시도
✅ 모든 과정 로그 기록
✅ 수동 개입 불필요

**다음 토요일 밤을 기다려보세요!** 🚀