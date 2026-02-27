# lotto-filter-api

로또 조합 필터 카운팅 백엔드 (FastAPI + numpy)

## 구조

- 서버 시작 시 8,145,060개 조합의 속성을 numpy 배열로 메모리에 로드
- 필터 조건을 numpy 마스킹으로 처리 → 요청당 0.1~0.5초 이내 응답

## 로컬 실행

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## API

### POST /api/count
필터 조건에 맞는 정확한 조합 수 반환

### GET /api/health
서버 상태 확인 (매트릭스 초기화 완료 여부)

## Render 배포

1. GitHub에 push
2. render.com → New Web Service → GitHub 연결
3. render.yaml 자동 감지됨

## 주의사항

- Render 무료 플랜: 15분 미사용 시 Sleep → 첫 요청 30~60초 소요
- 서버 시작 시 매트릭스 빌드에 약 60~120초 소요 (Render 무료 플랜 기준)
- 메모리 사용량: 약 650MB (numpy int16 기준)
