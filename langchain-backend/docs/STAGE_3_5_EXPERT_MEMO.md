# Stage 3-5: ExpertMemo 학습 시그널 신설

## 개요

사용자 전문가 메모를 학습 시그널로 활용하는 시스템 구축:
- Supabase 2 테이블 (expert_memos, expert_memo_history)
- 메모 → 90D feature 추출 (ExpertMemoFeatureExtractor)
- 메모 적중률 추적 + 신뢰도 동적 갱신 (ExpertMemoHistoryTracker)
- 메모 정합성 손실 (MemoConsistencyLoss)
- NumberRecommender 메모 자동 로드 통합

## 구성 요소

### A. Supabase 테이블

**expert_memos**
- `id`: UUID PK
- `target_round`: 메모 적용 회차
- `forced_includes`: 강제 추천 번호 (int[])
- `forced_excludes`: 강제 제외 번호 (int[])
- `confidence`: 사용자 신뢰도 (0~1)
- `domain_tags`: 자동 태깅 (text[])
- `memo_text`: 자연어 메모

**expert_memo_history**
- `memo_id`: FK → expert_memos
- `target_round`: 평가 회차
- `actual_numbers`: 실제 당첨번호
- `forced_includes_hit`: 적중 카운트
- `forced_excludes_correct`: 미당첨 카운트 (정답)
- `memo_score`: 회차별 적중률
- `memo_hit_rate_window`: 누적 50회 평균
- `memo_domain_confidence`: sigmoid 신뢰도

### B. 모듈

| 파일 | 역할 |
|---|---|
| `models/expert_memo_extractor.py` | 메모 → 90D feature (45D excludes + 45D includes) |
| `services/expert_memo_history.py` | 메모 적중률 추적 + 신뢰도 산출 |
| `pipeline/memo_loss.py` | Memo Consistency Loss (학습 시 보조 손실) |
| `models/number_recommender.py` | MemoLoader 통합 (자동 메모 조회) |

### C. 통합 흐름

1. **메모 작성** (프론트엔드 → Supabase)
   - 사용자가 target_round=1223에 대해 메모 작성
   - forced_includes=[3, 11], forced_excludes=[44, 45], confidence=0.8

2. **추천 생성** (NumberRecommender)
   ```python
   recommender = NumberRecommender()
   result = recommender.recommend(
       final_probs=...,
       filter_stats_result=...,
       predictor_pipeline_outputs=...,
       rankings=...,
       target_round=1223,  # 자동 메모 로드
       auto_load_memo=True,
   )
   ```
   - Hard Filter 1순위: forced_includes [3, 11] → 추천 5에 강제 포함
   - Hard Filter 1순위: forced_excludes [44, 45] → 제외 10에 강제 포함

3. **적중률 추적** (ExpertMemoHistoryTracker)
   ```python
   tracker = ExpertMemoHistoryTracker()
   record = tracker.update(
       target_round=1223,
       memo=loaded_memo,
       actual_winning_numbers=[4, 11, 17, 22, 32, 41],
   )
   # record['hit_rate'] = 0.5 (11 적중 / 2개)
   # record['memo_domain_confidence'] = 0.5 (sigmoid)
   ```

4. **학습 시 보조 손실** (PyTorch 모델)
   ```python
   from pipeline.memo_loss import memo_consistency_loss
   
   aux_loss = memo_consistency_loss(
       predictions=model_output,  # (B, 45) sigmoid 확률
       labels=target_labels,      # (B, 45) binary
       memo=loaded_memo,
       memo_confidence=0.8,
       weight=0.1,
   )
   total_loss = main_loss + aux_loss
   ```

## 마이그레이션 적용

### 방법 1: Supabase SQL Editor (권장)
1. https://supabase.com/dashboard → SQL Editor
2. `db/migrations/002_expert_memo_tables.sql` 내용 복사
3. 실행

### 방법 2: Supabase CLI
```bash
supabase db push --file db/migrations/002_expert_memo_tables.sql
```

### 방법 3: 검증 스크립트
```bash
python scripts/apply_expert_memo_migration.py
```

## 테스트

### e2e 테스트 (Supabase 필요)
```bash
python scripts/_test_expert_memo.py
```

검증 항목:
- expert_memos insert 성공
- NumberRecommender 자동 메모 로드
- forced_includes [3, 7] → 추천 5 포함
- forced_excludes [44, 45] → 제외 10 포함
- expert_memo_history 적중률 기록
- 50회 누적 전 confidence 기본값 (0.5)

### 로컬 smoke (Supabase 불필요)
```bash
cd langchain-backend
python models/expert_memo_extractor.py
python services/expert_memo_history.py
python pipeline/memo_loss.py
```

## 점진 도입 (마스터 플랜 #22)

- **초기 (50회 누적 전)**: memo_consistency_loss weight=0.0 (비활성)
- **50회 누적 후**: weight=0.1 (점진 활성)
- **confidence < 0.5**: Weak signal (Pillar 보강만, 강제 X)
- **confidence ≥ 0.5**: Strong signal (Hard Filter 1순위 강제)

## 다음 단계

- Stage 4-B: XAI Narrative (메모 시그널을 자연어로 설명)
- Stage 5: 프론트엔드 메모 작성 UI
- Stage 6: 도메인별 메모 신뢰도 분석 (domain_tags 활용)
