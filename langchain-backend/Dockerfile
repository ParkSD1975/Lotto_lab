FROM python:3.11-slim

WORKDIR /app

# torch CPU-only 먼저 설치 (CUDA 버전 제외: ~200MB vs ~900MB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# requirements.txt 복사 후 torch 제외하고 나머지 설치
COPY requirements.txt .
RUN grep -v "^torch" requirements.txt | pip install --no-cache-dir -r /dev/stdin

# 앱 코드 복사
COPY . .

EXPOSE 8000

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
