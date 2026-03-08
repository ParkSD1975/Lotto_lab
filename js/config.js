const CONFIG = {
    SUPABASE: {
        URL: 'https://dkcflmyoscudawleglzb.supabase.co',
        KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRrY2ZsbXlvc2N1ZGF3bGVnbHpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc1NDQ4OTAsImV4cCI6MjA4MzEyMDg5MH0.haAvbpScvMJv1uqH_tk-0fUlJNCpHnlWBtYzX6YFweo'
    },
    LANGCHAIN: {
        URL: 'https://lottolab-production-31e3.up.railway.app',
        ENABLED: true,
        TIMEOUT: 30000
    }
};

window.CONFIG = CONFIG;

// [New] AI Backend (LangChain) Configuration
// Python FastAPI 서버와의 통신 설정입니다.
window.LANGCHAIN_CONFIG = {
    URL: 'https://lottolab-production-31e3.up.railway.app', // Python 백엔드 주소 (Railway - No cold start)
    TIMEOUT: 30000,               // 타임아웃 (30초)
    ENABLED: true                 // AI 프록시 사용 여부
};
