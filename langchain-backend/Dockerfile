FROM python:3.11-slim

WORKDIR /app

# torch CPU-only 먼저 설치 (CUDA 버전 제외: ~200MB vs ~900MB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# requirements.txt 복사 후 torch 제외하고 나머지 설치
COPY requirements.txt .
RUN grep -v "^torch" requirements.txt | pip install --no-cache-dir -r /dev/stdin

# 앱 코드 복사
COPY . .

# .env 파일 직접 생성 (Supabase anon key는 프론트엔드에도 공개된 값)
# GOOGLE_API_KEY는 HF Space secret으로 주입되므로 여기서 제외
RUN echo "SUPABASE_URL=https://dkcflmyoscudawleglzb.supabase.co" > /app/.env && \
    echo "SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo" >> /app/.env

# Hugging Face Spaces는 포트 7860을 사용합니다
EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
