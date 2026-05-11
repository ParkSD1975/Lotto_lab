# Lotto_lab 패치 적용 가이드

> **작성일**: 2026-05-11  
> **근거**: `Lotto_lab_Root_Cause_Diagnosis.md` 진단 결과

---

## 📂 패치 목록

| 패치 | 대상 파일 | 영역 | 우선순위 | 상태 |
|------|----------|------|----------|------|
| **P1** | `models/number_recommender.py` | 빈도 페널티 | ★★★★★ | ✅ 작성됨 |
| **P2** | `routes/performance.py` | Fallback 가중치 | ★★★★☆ | ✅ 작성됨 |
| **P3** | `pipeline/weekly_pipeline_v2.py` | 추론 시 가중치 갱신 | ★★★★☆ | ✅ 작성됨 |
| **P4** | `services/veto_filler.py` (신규) | Veto 로직 | ★★★★☆ | ✅ 작성됨 |
| **P5-A** | `services/pillar_scorer.py` (신규) | 4-Pillar 구현 | ★★★☆☆ | ✅ 작성됨 |
| **P5-B** | DB SQL | 4-Pillar 임시 정리 | - | ✅ 작성됨 (택1) |

---

## 🗂 파일 구조

```
Lotto_lab_Patches/
├── README.md                          ← 본 문서 (시작점)
├── P1_number_recommender.md           ✅ 빈도 페널티
├── P2_performance_fallback.md         ✅ Fallback 가중치
├── P3_weekly_pipeline.md              ✅ 추론 시 가중치 갱신
├── P4_veto_filler.md                  ✅ Veto 로직 (신규 파일)
├── P5_optA_pillar_scorer.md           ✅ 4-Pillar 구현 (신규 파일)
└── P5_pillar_scores_cleanup.sql       ✅ 4-Pillar 임시 정리 (옵션 B)
```

> **P5는 두 가지 옵션 중 택1**:
> - **옵션 A** (`P5_optA_pillar_scorer.md`): 실제 구현 — 1일 소요  
> - **옵션 B** (`P5_pillar_scores_cleanup.sql`): NULL 정리 — 30분 소요  
> 첫 적용은 옵션 B 권장 (안전), 시간 여유 시 옵션 A로 교체

---

## ⚡ 적용 권장 순서

### Day 1
1. **P1**: 빈도 페널티 (30분 + 백테스트 1시간)
2. **P2**: Fallback 가중치 (10분)

### Day 2
3. **P3**: 추론 시 가중치 갱신 (2시간)
4. **P4**: Veto 로직 (2시간)

### Day 3
5. **P5**: 4-Pillar 정리 또는 구현
6. 통합 백테스트 (50회) → lift 측정

---

## 🔄 적용 전 공통 절차

### 1. 백업
```bash
cd lotto-ai-backend
git checkout -b patches/p1-frequency-penalty
git status   # clean 확인
```

### 2. 패치 적용
각 패치 .md 파일의 단계별 가이드 따라 수정

### 3. Smoke 테스트
```bash
python -m models.number_recommender   # P1
# 또는 각 패치별 smoke
```

### 4. 백테스트
```bash
python -m pipeline.weekly_pipeline_v2 --backtest --rounds 1173-1222
```

### 5. 효과 측정 SQL
```sql
-- favorite bias 해소 확인
SELECT 
  COUNT(*) FILTER (WHERE 18 = ANY(top_5)) * 100.0 / COUNT(*) as pct_18,
  COUNT(*) FILTER (WHERE 14 = ANY(top_5)) * 100.0 / COUNT(*) as pct_14,
  COUNT(*) FILTER (WHERE 43 = ANY(top_5)) * 100.0 / COUNT(*) as pct_43,
  AVG(top5_hit_count) as avg_hit
FROM weekly_predictions
WHERE target_round BETWEEN 1173 AND 1222;
```

목표:
- `pct_18` < 30%
- `avg_hit` ≥ 0.95

---

## ✅ 각 패치 적용 후 체크리스트

```
□ git diff 검토 — 의도한 변경만 포함
□ Smoke 테스트 통과
□ Unit 테스트 통과 (있다면)
□ 백테스트 실행
□ favorite bias 해소 확인
□ Top-5 hit lift 측정 (현재 0.78 → 목표 0.95+)
□ 3개+ 적중 빈도 확인 (현재 0건 → 목표 2~5건/50회)
□ git commit + 메시지에 패치 ID 포함
□ MASTER_PLAN.md 또는 변경 이력 업데이트
```

---

## 🔗 관련 문서

- `Lotto_lab_Root_Cause_Diagnosis.md` — 진단 보고서 (왜 이 패치들이 필요한가)
- `Lotto_lab_Logic_Enhancements.md` — 로드맵 (P → A → B → D → C → E → F)
- `Lotto_lab_DB_Consistency_Issues.md` — DB 변경 사항 (P5와 연결)

---

## 📝 변경 이력

| 일자 | 패치 | 상태 | 비고 |
|------|------|------|------|
| 2026-05-11 | P1 | ✅ 완료 | 빈도 페널티 (`number_recommender.py`) |
| 2026-05-11 | P2 | ✅ 완료 | Fallback 가중치 11-base (`performance.py`) |
| 2026-05-11 | P3 | ✅ 완료 | 추론 시 가중치 갱신 + EMA (`weekly_pipeline_v2.py`) |
| 2026-05-11 | P4 | ✅ 완료 | Veto 로직 (신규 `services/veto_filler.py`) |
| 2026-05-11 | P5-A | ✅ 완료 | 4-Pillar 구현 (신규 `services/pillar_scorer.py`) |
| 2026-05-11 | P5-B | ✅ 완료 | 4-Pillar 임시 정리 SQL |
