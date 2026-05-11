/**
 * deep_insight_panel.js  v3.0
 * Master Plan Stage 5-B — 11 base + 4 Pillar + ECharts 5 시각화
 * 22 분석 페이지 공통 컴포넌트.
 *
 * 디자인 (.impeccable.md 준수):
 *   - 라이트 모드 only, 프리미엄/심플/모던
 *   - 데이터 주인공, 컬러 1~2개 강조, 박스 grid 회피
 *   - 위계는 타이포(굵기·크기), 컬러 X
 *   - AI 슬롭/파스텔/컬러 아이콘 금지
 *
 * 4 영역 구조 (모든 22 페이지 공통):
 *   A: 헤더 — 지표명 + 신뢰도 (Pillar 4 합의도)
 *   B: 활성 모델 — 페이지 컨텍스트별 11 base 중 일부
 *   C: 4 Pillar 추천 5 + 제외 10 + XAI 카드
 *   D: Gemma 4 narrative — 흐름/추세/추천
 *
 * 사용법:
 *   <div id="dlInsightContainer" data-indicator="total_sum"></div>
 *   <script src="js/deep_insight_panel_v3.js"></script>
 *   <script>DeepInsightPanelV3.init({indicator: 'total_sum'});</script>
 *
 * v2 backward compat:
 *   DeepInsightPanel.render(containerId, filterKey, filterLabel) — 자동 v3 리다이렉트
 */
(function () {
    'use strict';

    // ────── 11 base 모델 메타 (데이터 라벨용) ──────
    // [Stage 1-4-D-2-fix-10] N-BEATS는 메인 1~45 영역에서 제외 (스칼라 분해 전용)
    //   - MODEL_META: 11 base 메타 유지 (백워드 호환)
    //   - MODEL_ORDER(메인 1~45 렌더용): nbeats 제외 → 10 base
    //   - INDICATOR_ACTIVE_MODELS: 스칼라 지표만 nbeats 활성, 나머지는 nbeats 미포함
    const MODEL_META = {
        xgboost:     { label: 'XGBoost',  token: '--c-xgb',     tag: '트리' },
        catboost:    { label: 'CatBoost', token: '--c-cat',     tag: '카테고리' },
        tabnet:      { label: 'TabNet',   token: '--c-tabnet',  tag: 'attention' },
        cnn:         { label: 'CNN',      token: '--c-cnn',     tag: '그리드' },
        gnn:         { label: 'GNN',      token: '--c-gnn',     tag: '그래프' },
        markov:      { label: 'Markov',   token: '--c-markov',  tag: '전이' },
        autoencoder: { label: 'AE',       token: '--c-ae',      tag: '이상치' },
        tft:         { label: 'TFT',      token: '--c-tft',     tag: '시계열' },
        nbeats:      { label: 'N-BEATS',  token: '--c-nbeats',  tag: '스칼라 분해' },
        mhn:         { label: 'MHN',      token: '--c-mhn',     tag: '메모리' },
        bayesian_nn: { label: 'Bayesian', token: '--c-bayesian',tag: '불확실성' },
    };

    // 메인 1~45 영역 — N-BEATS 제외 (10 base)
    const MODEL_ORDER = [
        'xgboost', 'catboost', 'tabnet',
        'cnn', 'gnn',
        'markov',
        'autoencoder',
        'tft',
        'mhn',
        'bayesian_nn',
    ];

    // 스칼라 시계열 분해 전용 모델 (보조 영역)
    const SCALAR_DECOMPOSITION_MODELS = ['nbeats'];
    const SCALAR_INDICATORS = new Set(['total_sum', 'tail_sum', 'ac_value']);

    // 지표별 활성 모델 매핑 (Master Plan 표 1)
    // 스칼라 지표(total_sum/tail_sum/ac_value)만 nbeats 활성 — 별도 분해 차트로 노출
    const INDICATOR_ACTIVE_MODELS = {
        total_sum:         ['xgboost','catboost','tabnet','tft','markov','autoencoder','gnn','bayesian_nn'],
        tail_sum:          ['xgboost','catboost','tabnet','tft','markov','autoencoder','gnn','cnn','bayesian_nn'],
        ac_value:          ['xgboost','tft','markov','catboost','bayesian_nn'],
        low_high:          ['xgboost','catboost','tabnet','markov','tft','gnn','bayesian_nn'],
        odd_even:          ['xgboost','catboost','tabnet','markov','tft','gnn','bayesian_nn'],
        carryover:         ['xgboost','catboost','gnn','markov','tft'],
        consecutive_number:['xgboost','catboost','gnn','markov','tft'],
        neighbor_number:   ['xgboost','catboost','gnn','markov','tft'],
        tail_digit:        ['xgboost','catboost','tabnet','markov','gnn','tft','autoencoder','bayesian_nn'],
        number_range:      ['xgboost','catboost','tabnet','markov','gnn','tft','bayesian_nn'],
        magic_square:      ['xgboost','catboost','tabnet','markov','gnn','tft','bayesian_nn'],
        lotto_paper:       ['xgboost','catboost','tabnet','cnn','gnn','markov','tft','bayesian_nn'],
        multiple:          ['xgboost','catboost','tabnet','markov','gnn','tft'],
        prime_number:      ['xgboost','catboost','markov','gnn','tft'],
        composite_number:  ['xgboost','catboost','markov','gnn','tft'],
        triangular_number: ['xgboost','catboost','markov','gnn','tft'],
        square_number:     ['xgboost','catboost','markov','gnn','tft'],
        twin_number:       ['xgboost','catboost','markov','gnn','tft'],
        missing:           ['xgboost','catboost','tabnet','gnn','markov','autoencoder','tft'],
        hot_cold:          ['xgboost','catboost','tabnet','gnn','markov','autoencoder','tft'],
        regression:        ['xgboost','catboost','tabnet','gnn','markov','tft','bayesian_nn','mhn'],
        custom_analysis:   MODEL_ORDER,
    };

    // 스칼라 지표일 때 별도 노출되는 보조 모델 (스칼라 시계열 분해)
    const INDICATOR_SCALAR_MODELS = {
        total_sum: SCALAR_DECOMPOSITION_MODELS,
        tail_sum:  SCALAR_DECOMPOSITION_MODELS,
        ac_value:  SCALAR_DECOMPOSITION_MODELS,
    };

    const INDICATOR_LABEL_KO = {
        total_sum:'총합', tail_sum:'끝수합', ac_value:'AC값',
        low_high:'고저', odd_even:'홀짝', carryover:'이월수',
        consecutive_number:'연번', neighbor_number:'이웃수',
        tail_digit:'끝수 분포', number_range:'번호대',
        magic_square:'9궁', lotto_paper:'로또용지',
        multiple:'배수', prime_number:'소수', composite_number:'합성수',
        triangular_number:'삼각수', square_number:'제곱수', twin_number:'동형수',
        missing:'미출현그룹', hot_cold:'핫콜드', regression:'회귀',
        custom_analysis:'커스텀 분석',
    };

    // ────── CSS 토큰 주입 (1회) ──────
    let _stylesInjected = false;
    function injectStyles() {
        if (_stylesInjected) return;
        _stylesInjected = true;

        const css = `
        :root {
            /* 11 모델 데이터 라벨 토큰 (UI 칠하기 X, 차트 라벨만) */
            --c-xgb: #3B82F6;        --c-cat: #14B8A6;        --c-tabnet: #A855F7;
            --c-cnn: #EC4899;        --c-gnn: #EF4444;
            --c-markov: #10B981;
            --c-ae: #8B5CF6;
            --c-tft: #F97316;        --c-nbeats: #06B6D4;
            --c-mhn: #84CC16;        --c-bayesian: #F59E0B;

            /* 라이트 프리미엄 팔레트 */
            --dl-bg:        #FAFAFA;
            --dl-surface:   #FFFFFF;
            --dl-border:    #E5E7EB;
            --dl-divider:   #F1F5F9;
            --dl-text:      #0F172A;
            --dl-text-mid:  #475569;
            --dl-text-soft: #94A3B8;
            --dl-accent:    #3B82F6;
            --dl-accent-hover: #2563EB;
            --dl-success:   #059669;
            --dl-danger:    #DC2626;

            /* 타이포 */
            --dl-font: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
            --dl-mono: 'Pretendard', ui-monospace, monospace;
        }

        .dl-v3 {
            font-family: var(--dl-font);
            color: var(--dl-text);
            background: var(--dl-bg);
            line-height: 1.5;
            container-type: inline-size;
            container-name: dlpanel;
        }

        /* 헤더 ─────────────────────────────────── */
        .dl-v3__header {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: end;
            gap: 1.5rem;
            padding: 1.75rem 0 1rem;
            border-bottom: 1px solid var(--dl-divider);
        }
        .dl-v3__title {
            font-size: clamp(1.5rem, 2.4vw, 2rem);
            font-weight: 700;
            letter-spacing: -0.025em;
            line-height: 1.2;
            margin: 0;
        }
        .dl-v3__subtitle {
            margin-top: 0.35rem;
            font-size: 0.875rem;
            color: var(--dl-text-mid);
            font-weight: 500;
        }
        .dl-v3__confidence {
            text-align: right;
        }
        .dl-v3__confidence-label {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--dl-text-soft);
            font-weight: 600;
        }
        .dl-v3__confidence-value {
            font-size: 1.75rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: var(--dl-text);
            margin-top: 0.15rem;
            line-height: 1;
        }
        .dl-v3__confidence-strength {
            margin-top: 0.25rem;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--dl-text-mid);
        }
        .dl-v3__confidence-strength--strong { color: var(--dl-success); }
        .dl-v3__confidence-strength--weak   { color: var(--dl-danger);  }

        /* 영역 B: 활성 모델 ────────────────────── */
        .dl-v3__models {
            margin-top: 1.5rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem 0.75rem;
            align-items: baseline;
        }
        .dl-v3__models-label {
            font-size: 0.75rem;
            color: var(--dl-text-soft);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
            margin-right: 0.5rem;
        }
        .dl-v3__model-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.25rem 0.6rem;
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--dl-text);
            border: 1px solid var(--dl-border);
            border-radius: 999px;
            background: var(--dl-surface);
            transition: border-color 200ms ease;
        }
        .dl-v3__model-chip:hover {
            border-color: var(--dl-text-mid);
        }
        .dl-v3__model-dot {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: currentColor;
            flex-shrink: 0;
        }
        .dl-v3__model-tag {
            font-size: 0.7rem;
            color: var(--dl-text-soft);
            font-weight: 500;
        }

        /* 영역 C: Pillar + 추천/제외 ─────────────── */
        .dl-v3__pillars {
            margin-top: 2rem;
            display: grid;
            grid-template-columns: minmax(200px, 280px) 1fr;
            gap: 2.5rem;
            align-items: start;
        }
        @container dlpanel (max-width: 720px) {
            .dl-v3__pillars { grid-template-columns: 1fr; gap: 1.5rem; }
        }
        .dl-v3__pillar-stack {
            display: grid;
            gap: 1rem;
        }
        .dl-v3__pillar {
            display: grid;
            grid-template-columns: 36px 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--dl-divider);
        }
        .dl-v3__pillar:last-child { border-bottom: 0; }
        .dl-v3__pillar-key {
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            color: var(--dl-text-soft);
        }
        .dl-v3__pillar-name {
            font-size: 0.875rem;
            color: var(--dl-text);
            font-weight: 500;
        }
        .dl-v3__pillar-bar {
            grid-column: 1 / -1;
            height: 2px;
            background: var(--dl-divider);
            border-radius: 1px;
            overflow: hidden;
            margin-top: 0.4rem;
        }
        .dl-v3__pillar-bar-fill {
            height: 100%;
            background: var(--dl-text);
            transition: width 600ms cubic-bezier(0.16, 1, 0.3, 1);
        }
        .dl-v3__pillar-value {
            font-size: 0.75rem;
            font-variant-numeric: tabular-nums;
            font-weight: 600;
            color: var(--dl-text-mid);
        }

        /* 추천/제외 리스트 ──────────────── */
        .dl-v3__numbers {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }
        @container dlpanel (max-width: 720px) {
            .dl-v3__numbers { grid-template-columns: 1fr; }
        }
        .dl-v3__numbers-section h3 {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--dl-text-soft);
            font-weight: 600;
            margin: 0 0 1rem;
        }
        .dl-v3__number-item {
            display: grid;
            grid-template-columns: 44px 1fr auto;
            gap: 0.875rem;
            align-items: center;
            padding: 0.625rem 0;
            border-bottom: 1px solid var(--dl-divider);
            cursor: pointer;
            transition: background 200ms ease;
        }
        .dl-v3__number-item:hover {
            background: var(--dl-divider);
        }
        .dl-v3__number-num {
            font-size: 1.25rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: var(--dl-text);
            text-align: center;
        }
        .dl-v3__number-label {
            font-size: 0.8rem;
            color: var(--dl-text-mid);
            line-height: 1.4;
        }
        .dl-v3__number-badge {
            font-size: 0.7rem;
            color: var(--dl-text-soft);
            font-variant-numeric: tabular-nums;
            font-weight: 600;
        }
        .dl-v3__number-badge--memo {
            color: var(--dl-accent);
        }
        .dl-v3__number-badge--rule {
            color: var(--dl-danger);
        }

        /* XAI 카드 (펼침) ───────────── */
        .dl-v3__xai {
            display: none;
            margin: 0.5rem 0 1rem;
            padding: 1rem 0;
            border-top: 1px solid var(--dl-divider);
            border-bottom: 1px solid var(--dl-divider);
            font-size: 0.8rem;
            color: var(--dl-text-mid);
            line-height: 1.55;
        }
        .dl-v3__xai.open { display: block; }
        .dl-v3__xai-row {
            display: grid;
            grid-template-columns: 90px 1fr;
            gap: 0.75rem;
            margin-bottom: 0.4rem;
        }
        .dl-v3__xai-key {
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--dl-text-soft);
            font-weight: 600;
        }
        .dl-v3__xai-value { color: var(--dl-text); }

        /* 영역 D: narrative ─────────────────────── */
        .dl-v3__narrative {
            margin-top: 2rem;
            padding-top: 2rem;
            border-top: 1px solid var(--dl-divider);
            display: grid;
            gap: 1.25rem;
        }
        .dl-v3__narr-section {
            display: grid;
            grid-template-columns: 80px 1fr;
            gap: 1rem;
        }
        .dl-v3__narr-key {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--dl-text-soft);
            font-weight: 700;
            padding-top: 0.15rem;
        }
        .dl-v3__narr-body {
            font-size: 0.95rem;
            line-height: 1.65;
            color: var(--dl-text);
            font-weight: 400;
        }
        .dl-v3__narr-body--accent {
            font-weight: 600;
            font-size: 1.05rem;
        }

        /* ECharts 컨테이너 ───────────────────── */
        .dl-v3__chart {
            margin-top: 2rem;
            height: 240px;
        }
        .dl-v3__chart--small { height: 120px; }

        /* 로딩 / 에러 ──────────────────────────── */
        .dl-v3__loading,
        .dl-v3__error {
            padding: 2rem 0;
            text-align: center;
            font-size: 0.875rem;
            color: var(--dl-text-soft);
        }
        .dl-v3__error { color: var(--dl-danger); }
        .dl-v3__loading::before {
            content: '';
            display: inline-block;
            width: 12px; height: 12px;
            margin-right: 0.5rem;
            border: 2px solid var(--dl-divider);
            border-top-color: var(--dl-text-mid);
            border-radius: 50%;
            animation: dl-v3-spin 0.8s linear infinite;
            vertical-align: -2px;
        }
        @keyframes dl-v3-spin { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) {
            .dl-v3__pillar-bar-fill { transition: none; }
            .dl-v3__loading::before { animation: none; }
        }
        `;
        const style = document.createElement('style');
        style.id = 'dl-v3-styles';
        style.textContent = css;
        document.head.appendChild(style);
    }

    // ────── 데이터 페치 (V4 API + 캐시) ──────
    const _cache = new Map();

    async function fetchAnalysis(indicator) {
        if (_cache.has(indicator)) return _cache.get(indicator);
        const baseUrl = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
        try {
            const res = await fetch(`${baseUrl}/api/v4/insight/${indicator}`, {
                signal: AbortSignal.timeout(5000),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _cache.set(indicator, data);
            return data;
        } catch (e) {
            console.warn(`[DeepInsightPanelV3] fetch fail (${indicator}):`, e);
            return null;
        }
    }

    // ────── 렌더 헬퍼 ──────
    function el(tag, cls, html) {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (html != null) node.innerHTML = html;
        return node;
    }

    function renderHeader(container, data, indicator) {
        const indicatorLabel = INDICATOR_LABEL_KO[indicator] || indicator;
        const consensus = (data && data.consensus_strength) || 'N/A';
        const confidence = (data && data.global_confidence) || 0;

        const header = el('header', 'dl-v3__header');
        const left = el('div');
        left.appendChild(el('h2', 'dl-v3__title', indicatorLabel));
        left.appendChild(el('p', 'dl-v3__subtitle',
            `메인 10 모델 합의 분석 · ${data && data.target_round ? '회차 ' + data.target_round : '최신 회차'}`));

        const right = el('div', 'dl-v3__confidence');
        right.appendChild(el('div', 'dl-v3__confidence-label', '신뢰도'));
        right.appendChild(el('div', 'dl-v3__confidence-value',
            (confidence * 100).toFixed(1) + '<span style="font-size:0.7em;color:var(--dl-text-soft);">%</span>'));
        const strengthCls = consensus === '강' ? 'dl-v3__confidence-strength--strong'
                          : consensus === '약' ? 'dl-v3__confidence-strength--weak' : '';
        right.appendChild(el('div', 'dl-v3__confidence-strength ' + strengthCls,
            'Pillar 4 합의 ' + consensus));

        header.append(left, right);
        container.appendChild(header);
    }

    function renderActiveModels(container, indicator) {
        const active = INDICATOR_ACTIVE_MODELS[indicator] || MODEL_ORDER;
        const wrap = el('div', 'dl-v3__models');
        wrap.appendChild(el('span', 'dl-v3__models-label', `활성 모델 ${active.length}`));

        active.forEach(name => {
            const meta = MODEL_META[name];
            if (!meta) return;
            const chip = el('span', 'dl-v3__model-chip');
            const dot = el('span', 'dl-v3__model-dot');
            dot.style.color = `var(${meta.token})`;
            chip.append(dot, document.createTextNode(meta.label));
            chip.appendChild(el('span', 'dl-v3__model-tag', meta.tag));
            wrap.appendChild(chip);
        });
        container.appendChild(wrap);

        // 스칼라 지표는 별도 보조 영역 — 스칼라 시계열 분해 모델
        const scalarModels = INDICATOR_SCALAR_MODELS[indicator];
        if (scalarModels && scalarModels.length) {
            const auxWrap = el('div', 'dl-v3__models');
            auxWrap.style.marginTop = '0.5rem';
            auxWrap.appendChild(el('span', 'dl-v3__models-label', '스칼라 시계열 분해'));
            scalarModels.forEach(name => {
                const meta = MODEL_META[name];
                if (!meta) return;
                const chip = el('span', 'dl-v3__model-chip');
                const dot = el('span', 'dl-v3__model-dot');
                dot.style.color = `var(${meta.token})`;
                chip.append(dot, document.createTextNode(meta.label));
                chip.appendChild(el('span', 'dl-v3__model-tag', meta.tag));
                auxWrap.appendChild(chip);
            });
            container.appendChild(auxWrap);
        }
    }

    function renderPillars(container, data) {
        const pillars = (data && data.pillars) || {};
        const PILLAR_DEFS = [
            { key: 'ENS', name: '앙상블 확률', value: pillars.ens },
            { key: 'FLT', name: '필터 통과도', value: pillars.flt },
            { key: 'STA', name: '개별 상태',   value: pillars.sta },
            { key: 'CNS', name: '모델 합의',   value: pillars.cns },
        ];

        const numbers = el('div', 'dl-v3__numbers');

        // Pillar 게이지
        const stack = el('div', 'dl-v3__pillar-stack');
        PILLAR_DEFS.forEach(p => {
            const wrap = el('div');
            const item = el('div', 'dl-v3__pillar');
            item.appendChild(el('div', 'dl-v3__pillar-key', p.key));
            item.appendChild(el('div', 'dl-v3__pillar-name', p.name));
            const valTxt = (typeof p.value === 'number') ? (p.value * 100).toFixed(0) + '%' : '—';
            item.appendChild(el('div', 'dl-v3__pillar-value', valTxt));
            wrap.appendChild(item);

            const bar = el('div', 'dl-v3__pillar-bar');
            const fill = el('div', 'dl-v3__pillar-bar-fill');
            const w = (typeof p.value === 'number') ? (p.value * 100) : 0;
            requestAnimationFrame(() => { fill.style.width = w + '%'; });
            bar.appendChild(fill);
            wrap.appendChild(bar);
            stack.appendChild(wrap);
        });

        // 추천 5 + 제외 10
        const lists = el('div');
        lists.style.display = 'grid';
        lists.style.gridTemplateColumns = '1fr 1fr';
        lists.style.gap = '2rem';

        lists.appendChild(_renderNumberList('추천', (data && data.recommendations) || [], 'recommend'));
        lists.appendChild(_renderNumberList('제외', (data && data.exclusions) || [], 'exclude'));

        const wrap = el('div', 'dl-v3__pillars');
        wrap.append(stack, lists);
        container.appendChild(wrap);
    }

    function _renderNumberList(title, items, type) {
        const sec = el('div', 'dl-v3__numbers-section');
        sec.appendChild(el('h3', null, title + ' ' + items.length));

        if (!items.length) {
            sec.appendChild(el('p', null,
                '<span style="color:var(--dl-text-soft);font-size:0.8rem;">데이터 없음</span>'));
            return sec;
        }

        items.forEach(it => {
            const item = el('div', 'dl-v3__number-item');
            item.appendChild(el('div', 'dl-v3__number-num', String(it.number)));
            const lblText = type === 'recommend'
                ? (it.narrative_seed || it.label || '')
                : (it.exclude_reason_label || it.exclude_reason || '');
            item.appendChild(el('div', 'dl-v3__number-label', lblText));

            // 배지
            let badge = '';
            let badgeCls = 'dl-v3__number-badge';
            if (it.memo_forced) { badge = '메모'; badgeCls += ' dl-v3__number-badge--memo'; }
            else if (it.force_exclude) { badge = '룰'; badgeCls += ' dl-v3__number-badge--rule'; }
            else if (typeof it.score === 'number') { badge = it.score.toFixed(2); }
            item.appendChild(el('div', badgeCls, badge));

            // XAI 펼침
            const xai = el('div', 'dl-v3__xai');
            if (it.xai) _populateXai(xai, it.xai);
            item.addEventListener('click', () => xai.classList.toggle('open'));

            sec.appendChild(item);
            sec.appendChild(xai);
        });
        return sec;
    }

    function _populateXai(node, xai) {
        const rows = [];
        if (xai.layer_2_pillar_gauges) {
            const g = xai.layer_2_pillar_gauges;
            rows.push(['ENS / FLT / STA / CNS',
                `${(g.ENS*100|0)}% · ${(g.FLT*100|0)}% · ${(g.STA*100|0)}% · ${(g.CNS*100|0)}%`]);
        }
        if (xai.auto_rule_triggers && xai.auto_rule_triggers.length) {
            rows.push(['자동 룰', xai.auto_rule_triggers.map(t => t.reason).join(', ')]);
        }
        if (xai.memo_signals && (xai.memo_signals.forced_inc || xai.memo_signals.forced_exc)) {
            rows.push(['메모', xai.memo_signals.forced_inc ? '강제 추천' : '강제 제외']);
        }
        rows.forEach(([k, v]) => {
            const row = el('div', 'dl-v3__xai-row');
            row.appendChild(el('div', 'dl-v3__xai-key', k));
            row.appendChild(el('div', 'dl-v3__xai-value', v));
            node.appendChild(row);
        });
    }

    function renderNarrative(container, data) {
        const narr = (data && data.narrative) || {};
        const wrap = el('section', 'dl-v3__narrative');

        const sections = [
            ['흐름', narr.flow || narr.signal, false],
            ['추세', narr.trend || narr.rationale, false],
            ['추천', narr.recommendation || narr.conclusion, true],
        ];
        sections.forEach(([k, body, accent]) => {
            const row = el('div', 'dl-v3__narr-section');
            row.appendChild(el('div', 'dl-v3__narr-key', k));
            const bodyCls = 'dl-v3__narr-body' + (accent ? ' dl-v3__narr-body--accent' : '');
            row.appendChild(el('div', bodyCls,
                body || '<span style="color:var(--dl-text-soft);">분석 중</span>'));
            wrap.appendChild(row);
        });
        container.appendChild(wrap);
    }

    function renderChart(container, data, indicator) {
        if (typeof echarts === 'undefined') return;
        if (!data || !data.timeseries) return;

        const chartDiv = el('div', 'dl-v3__chart');
        chartDiv.id = 'dl-v3-chart-' + indicator;
        container.appendChild(chartDiv);

        const chart = echarts.init(chartDiv, null, { renderer: 'svg' });
        chart.setOption({
            backgroundColor: 'transparent',
            grid: { left: 40, right: 16, top: 24, bottom: 28 },
            xAxis: {
                type: 'category',
                data: data.timeseries.x,
                axisLine: { lineStyle: { color: '#E5E7EB' } },
                axisTick: { show: false },
                axisLabel: { color: '#94A3B8', fontFamily: 'Pretendard', fontSize: 11 },
            },
            yAxis: {
                type: 'value',
                splitLine: { lineStyle: { color: '#F1F5F9' } },
                axisLine: { show: false },
                axisLabel: { color: '#94A3B8', fontFamily: 'Pretendard', fontSize: 11 },
            },
            tooltip: { trigger: 'axis', backgroundColor: '#FFFFFF',
                       borderColor: '#E5E7EB', textStyle: { color: '#0F172A' } },
            series: [{
                type: 'line',
                data: data.timeseries.y,
                smooth: true,
                symbol: 'none',
                lineStyle: { color: '#3B82F6', width: 2 },
                areaStyle: { color: 'rgba(59,130,246,0.06)' },
            }],
        });
        // 반응형
        new ResizeObserver(() => chart.resize()).observe(chartDiv);
    }

    // ────── 메인 진입점 ──────
    const DeepInsightPanelV3 = {
        async init(opts) {
            const indicator = (opts && opts.indicator)
                || (document.getElementById('dlInsightContainer')
                    ? document.getElementById('dlInsightContainer').dataset.indicator
                    : null);
            if (!indicator) {
                console.warn('[DeepInsightPanelV3] indicator missing');
                return;
            }
            const containerId = (opts && opts.containerId) || 'dlInsightContainer';
            const container = document.getElementById(containerId);
            if (!container) return;

            injectStyles();
            container.classList.add('dl-v3');
            container.innerHTML = '<div class="dl-v3__loading">분석 데이터 로딩 중</div>';

            const data = await fetchAnalysis(indicator);
            if (!data) {
                container.innerHTML = '<div class="dl-v3__error">분석 데이터를 불러올 수 없습니다.</div>';
                return;
            }

            container.innerHTML = '';
            renderHeader(container, data, indicator);
            renderActiveModels(container, indicator);
            renderPillars(container, data);
            renderChart(container, data, indicator);
            renderNarrative(container, data);
        },

        // v2 backward compat
        render(containerId, filterKey/*, filterLabel*/) {
            this.init({ containerId, indicator: filterKey });
        },
    };

    window.DeepInsightPanelV3 = DeepInsightPanelV3;
    // v2 shim — 기존 호출자 깨지지 않게
    window.DeepInsightPanel = window.DeepInsightPanel || DeepInsightPanelV3;

    // [fix-236] PremiumInsightPanel가 로드되어 있으면 자동 init 스킵
    // → v3 panel이 먼저 미완성 인사이트 그리는 깜빡거림 차단
    document.addEventListener('DOMContentLoaded', () => {
        if (window.PremiumInsightPanel) {
            // PremiumInsightPanel가 이 페이지를 렌더할 예정 — v3 자동 init 비활성화
            return;
        }
        const node = document.getElementById('dlInsightContainer');
        if (node && node.dataset.indicator) {
            DeepInsightPanelV3.init({ indicator: node.dataset.indicator });
        }
    });
})();
