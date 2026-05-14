const CONFIG = {
    SUPABASE: {
        URL: 'https://dkcflmyoscudawleglzb.supabase.co',
        KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo'
    },
    LANGCHAIN: {
        URL: 'https://parksungdeok-lotto-ai-backend.hf.space',  // [2026-05-14] localhost:8000 → HF Spaces 통일 (ERR_CONNECTION_REFUSED fix)
        ENABLED: true,
        TIMEOUT: 60000
    }
};

window.CONFIG = CONFIG;

// [New] AI Backend (LangChain) Configuration
// Python FastAPI 서버와의 통신 설정입니다.
window.LANGCHAIN_CONFIG = {
    URL: 'https://parksungdeok-lotto-ai-backend.hf.space', // Python 백엔드 주소 (HF Spaces)
    TIMEOUT: 60000,               // 타임아웃 (60초)
    ENABLED: true                 // AI 프록시 사용 여부
};
