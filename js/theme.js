// Tailwind CSS 설정 (CDN 방식용 레거시 코드 - 정적 빌드 환경에서는 설정 파일로 통합됨)
if (typeof tailwind !== 'undefined') {
    tailwind.config = {
        darkMode: "class",
        theme: {
            extend: {
                colors: {
                    "active-green": "#E6FFED",
                    "active-text": "#16A34A",
                    "lotto-blue": "#3B82F6",
                    "lotto-orange": "#F97316",
                    "lotto-pink": "#EC4899",
                    "lotto-purple": "#8B5CF6"
                },
                fontFamily: {
                    "sans": ["Pretendard", "Inter", "sans-serif"],
                },
            },
        },
    };
}

// Chart.js 전역 기본 설정 (Chart 객체가 로드된 경우에만)
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = "'Pretendard', 'Inter', sans-serif";
    Chart.defaults.color = '#6B7280';
    Chart.defaults.scale.grid.color = '#F3F4F6';

    // 데이터라벨 플러그인 설정 (옵션)
    if (typeof ChartDataLabels !== 'undefined') {
        Chart.register(ChartDataLabels);
        Chart.defaults.set('plugins.datalabels', {
            color: '#fff',
            font: { weight: 'bold' },
            display: 'auto'
        });
    }
}