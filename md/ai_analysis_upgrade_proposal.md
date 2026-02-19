# 🚀 Lotto AI Master Plan v3.0 (Upgrade Proposal)

**작성자**: Chief AI Architect  
**날짜**: 2026-02-01  
**기반 문서**: `ai_analysis_master_plan_v2.md`

## 🧐 전문가 진단 (Assessment)

기존 `v2` 계획서는 **1,150회 전체 데이터 학습**과 **LSTM/CNN 하이브리드 모델**이라는 강력한 **'예측 엔진(Engine)'** 구축에 초점이 맞춰져 있습니다. 이는 매우 훌륭한 기술적 토대입니다.

하지만, **'사용자 경험(UX)'**과 **'시스템 자율성(Autonomy)'** 측면에서 보강이 필요합니다. "최고의 기획자이자 개발자"로서 다음 3가지 핵심 업그레이드를 제안합니다.

---

## 🔥 핵심 업그레이드 전략

### 1. Agentic AI Analyst (능동형 분석가 도입)
> **"단순한 결과 통보가 아니라, 사용자와 함께 분석하는 파트너"**

기존 계획의 `Layer 4: LLM 해석`은 정적인 텍스트 생성에 그칩니다. 이를 **Interactive Agent**로 격상해야 합니다.

*   **기능**: 사용자가 자연어로 질문하면, DB(`stats_summary`, `ai_predictions`)를 **실시간 조회(RAG)**하여 답변.
*   **시나리오**:
    *   사용자: "이번 주 10번대 흐름이 어때?"
    *   AI: (DB 조회 후) "최근 5주간 10번대가 평균 2.5개 출현하여 과열 상태입니다. LSTM 모델도 10번대 비중 축소를 권장하고 있습니다."
*   **구현**: `custom_analysis.js`의 프롬프트 분석 기능을 확장하여, 분석 보고서 생성형이 아닌 **대화형 인터페이스** 구축.

### 2. Supabase-Native Processing (서버리스/자율화)
> **"로컬 파이썬 스크립트 의존성 제거"**

기존 계획은 `update_features.py` 등 로컬 스크립트 실행이 필수적입니다. 이는 자동화에 약점이 될 수 있습니다.

*   **변경**: 피처 엔지니어링 로직을 **Supabase Database Function (PL/pgSQL)** 또는 **Edge Function (Deno/Python)**으로 이관.
*   **이점**:
    1.  데이터 입력(Insert) 즉시 피처 자동 계산 (Trigger).
    2.  로컬 PC가 꺼져 있어도 클라우드 상에서 24시간 분석 가능.
    3.  웹 앱에서 버튼 하나로 "전체 재분석" 실행 가능.

### 3. Hybrid Feature Injection (커스텀 룰의 모델 반영)
> **"사용자의 직관을 AI 모델의 입력으로"**

우리가 방금 만든 **AI Custom Analysis (수식, 필터)** 기능을 딥러닝 모델과 분리하지 말고 통합해야 합니다.

*   **아이디어**: 사용자가 만든 'Custom Rule'의 적중 여부를 **피처 벡터(Feature Vector)**로 모델에 주입.
*   **효과**:
    *   "내가 만든 '날짜 끝수' 규칙이 요즘 잘 맞네?" → LSTM이 이를 감지하고 가중치 부여.
    *   사용자의 직관과 AI의 연산력이 결합된 진정한 하이브리드 모델.

---

## 🛠 수정된 아키텍처 (v3.0)

```mermaid
graph TD
    User[사용자] --> Web[웹 대시보드 (Next.js/HTML)]
    
    subgraph "Supabase Cloud (Autonomous Core)"
        DB[(PostgreSQL)]
        Edge[Edge Functions]
        
        DB -->|Real-time| Edge
        Edge -->|Autocalc| Features[Lotto Features]
        Features -->|Input| AI_Model[LSTM/XGBoost (On Edge)]
    end
    
    subgraph "Agentic Layer"
        Chat[Chat Interface]
        LLM[LLM (Claude/GPT)]
        
        User --> Chat
        Chat --> LLM
        LLM -->|Query| DB
        LLM -->|Execute| Edge
    end
    
    Web --> Chat
    Web --> DB
```

## ✅ 실행 로드맵 (Action Items)

1.  **DB 스키마 최적화**: `v2`의 `lotto_features` 테이블을 `lotto_draws`의 **Generated Column** 또는 **Trigger**로 구현 가능한지 검토.
2.  **Edge Prediction**: 가벼운 예측 모델(XGBoost 등)을 우선 Edge Function에 배포하여 **즉시 예측** 시스템 구축. (Heavy LSTM은 백그라운드 배치로 유지)
3.  **Custom Analysis 연동**: `ai_custom_analyses` 테이블의 데이터를 조회하여, 현재 가장 적중률 높은 '사용자 룰'을 메인 대시보드에 추천.

이 계획으로 진행하시겠습니까? 승인하시면 **DB 스키마 최적화**부터 즉시 착수하겠습니다.
