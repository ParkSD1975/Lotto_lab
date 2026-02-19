# 🎱 로또 AI 통합 개발 마스터플랜 (Lotto AI Master Plan)

## 1. 프로젝트 개요
* **목표**: 기존 통계적 분석 방식에 **RAG(검색 증강 생성)** 및 **딥러닝(LSTM/XGBoost)** 기술을 접목하여 고도화된 로또 번호 예측 및 분석 시스템 구축
* **핵심 가치**: 사용자 정의 분석(Custom Analysis)의 자동 학습화 및 과거 패턴 기반의 정밀 분석 제공

## 2. 시스템 아키텍처
### 2.1 전체 구조
`Client (HTML/JS)` ↔ `AI Proxy (Router)` ↔ `Backend (FastAPI/LangChain)` ↔ `Database (Supabase)`

### 2.2 기술 스택
* **Frontend**: HTML5, Vanilla JS, Tailwind CSS
* **Backend**: Python FastAPI (LangChain 프레임워크 사용)
* **AI Engine**: 
    * LLM: Google Gemini 2.0 Flash (생성 및 추론)
    * Embedding: Google text-embedding-004
    * Deep Learning: PyTorch (LSTM), XGBoost (정형 데이터 분석)
* **Database**: Supabase (PostgreSQL + pgvector)
* **Vector Store**: ChromaDB (로컬) 또는 Supabase Vector

## 3. 데이터베이스 설계 (Supabase)
### 3.1 핵심 테이블
1.  **`lotto_draws`**: 로또 회차별 당첨 번호 및 파생 변수(총합, 홀짝 등) 저장
2.  **`ai_custom_analyses`**: 사용자가 생성한 커스텀 분석 규칙 저장
3.  **`analysis_history`**: 커스텀 분석의 회차별 적중 이력 (딥러닝 학습 데이터로 활용)
4.  **`ai_predictions`**: AI 모델(LSTM/XGBoost)이 생성한 예측 결과 저장

## 4. 핵심 기능 명세
### 4.1 RAG 기반 분석 (Retrieval-Augmented Generation)
* 사용자 질문 또는 분석 요청 시, 과거 1,200회차 데이터 중 가장 유사한 패턴(벡터 유사도)을 검색하여 LLM에 근거로 제공.
* **구현 파일**: `rag/retriever.py`, `chains/analysis_chain.py`

### 4.2 딥러닝 예측 파이프라인
* **LSTM**: 시계열 데이터(번호의 흐름) 학습 및 예측
* **XGBoost**: 다양한 파생 변수(홀짝, 합계, AC값 등)를 기반으로 번호별 출현 확률 예측
* **앙상블**: 두 모델의 결과를 결합하여 최종 추천 번호 산출
* **자동화**: 매주 새로운 회차 업데이트 시 자동 재학습 (`scripts/train_models.py`)

### 4.3 커스텀 분석 시스템 (Custom Analysis)
* 사용자가 자연어 또는 UI로 자신만의 분석 규칙 생성 (예: "피보나치 수열과 소수 3개 이상 조합")
* 생성 즉시 과거 모든 회차에 대해 시뮬레이션(Back-testing) 수행 및 결과 DB 저장
* 이 결과를 딥러닝 모델의 새로운 피처(Feature)로 자동 반영

## 5. 단계별 구현 로드맵
* **Phase 1: 인프라 구축** (DB 스키마 확정, 백엔드 서버 기본 설정)
* **Phase 2: RAG 시스템 구현** (데이터 벡터화, 검색기 구현, LLM 연동)
* **Phase 3: 딥러닝 모델 통합** (학습 파이프라인 구축, 예측 API 개발)
* **Phase 4: 프론트엔드 연동** (AIProxy 적용, 분석 리포트 UI 개선)
* **Phase 5: 자동화 및 최적화** (매주 자동 업데이트 스크립트, 성능 튜닝)

---
*Last Updated: 2026-02-08*