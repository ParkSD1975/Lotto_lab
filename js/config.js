const CONFIG = {
    SUPABASE: {
        URL: 'https://dkcflmyoscudawleglzb.supabase.co',
        KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo'
    },
    LANGCHAIN: {
        URL: 'http://localhost:8000',  // [2026-05-15] 사용자 명시: 전부 로컬 백엔드 강제
        ENABLED: true,
        TIMEOUT: 60000
    }
};

window.CONFIG = CONFIG;

// [2026-05-15] AI Backend = 항상 로컬 (uvicorn :8000)
//   환경 분기 폐기. 사용자가 로컬 백엔드 실행 필수:
//     cd langchain-backend && python -m uvicorn main:app --port 8000
window.LANGCHAIN_CONFIG = {
    URL: 'http://localhost:8000',
    TIMEOUT: 60000,
    ENABLED: true,
    _resolvedFor: 'local-forced',
};
