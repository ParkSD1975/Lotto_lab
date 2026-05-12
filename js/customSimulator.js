/**
 * 커스텀 시뮬레이터 (v4 - 프리미엄 미니멀 디자인)
 *
 * 단계:
 *   S1 (현재): 디자인 시스템 + 페이지 골격 + 동행복권 즉시 로딩 placeholder
 *   S2: 동행복권 회차 리스트 가상 스크롤
 *   S3: DB chip 토글 동작
 *   S4-S6: 토큰 팔레트 + chip 시퀀스 빌더 + 보정 로직
 *   S7: 실시간 미리보기
 *   S8: 프리셋 + 저장된 필터
 *   S9-S10: 저장 모달 + customAnalysis 통합
 *   S11-S12: 전체 시뮬레이션 + 반응형
 *
 * 보존:
 *   기존 tokenize / evaluateSequential / normalize 핵심 연산 로직
 *   (S4-S6에서 확장: 끝수, 보너스, 일자, 자릿합 등)
 */

const CustomSim = {
    // ── State ─────────────────────────────────────────────────
    draws: [],                  // 현재 선택된 DB의 draw list (round DESC 정렬)
    lotteries: [],              // 해외 로또 메타 정보
    currentDB: 'korea',         // 활성 DB ID
    selectedRound: null,        // 미리보기 기준 회차 (null = 최신)
    windowN: 3,                 // 슬라이딩 윈도우

    // v5-multi — 다중 워크스페이스 모델
    workspaces: [               // [{id, label, cards, transforms, mode}, ...]
        {
            id: 'ws-1',
            label: 'W1',
            cards: [],
            transforms: [],
            mode: 'auto',       // 'auto' | 'set' | 'scalar'
        }
    ],
    activeWsId: 'ws-1',         // 드래그 타겟 워크스페이스 ID
    combineOps: [],             // [{ leftWsId, op, rightWsId }] — ws간 결합 연산 (좌→우 누적)
    combinePostTransforms: [],  // [{op, value}] — 결합 완료 후 추가 변환 (e.g. %10)
    combinePostExpand: false,   // 결합값 끝수 → 해당 끝수의 1~45 번호 전체로 expand
    selectionMode: 'line',      // 'line' | 'num' — 좌측에서 드래그 시 본번호 전체 vs 단일 번호
    dataMode: 'rounds',         // 'rounds' | 'tails' — 좌측 패널 표시 모드
    patternDetected: null,      // 자동 감지된 패턴 정보 (적용 대기)
    formulaSteps: [],           // 호환성 — 저장 시 패턴 표현으로 변환

    // ── 국가 정보 ────────────────────────────────────────────────
    COUNTRY_FLAGS: {
        AT: '🇦🇹', AU: '🇦🇺', BE: '🇧🇪', HR: '🇭🇷', HU: '🇭🇺', NL: '🇳🇱', PH: '🇵🇭',
        KR: '🇰🇷', US: '🇺🇸', JP: '🇯🇵', GB: '🇬🇧', CN: '🇨🇳',
    },
    COUNTRY_NAMES: {
        AT: '오스트리아', AU: '호주', BE: '벨기에', HR: '크로아티아', HU: '헝가리',
        NL: '네덜란드', PH: '필리핀', KR: '한국', US: '미국', JP: '일본', GB: '영국',
    },

    // ── Init (S1-S10) ───────────────────────────────────────────
    init: async () => {
        console.log('[CustomSim v5-multi] 초기화 시작');

        try {
            // 1. GNB
            if (window.Layout && window.Layout.loadGNB) {
                await window.Layout.loadGNB();
            }

            // 2. DB selector 이벤트
            CustomSim._bindDBSelector();

            // 3. (제거됨) 슬라이딩 윈도우 N — 시뮬레이션 설정 영역 폐기로 더 이상 호출 안 함

            // 4. v5-multi — 작업 공간 (드래그앤드롭 + 패턴 감지) 바인딩
            CustomSim._bindWorkspace();

            // 4b. 워크스페이스 초기 렌더
            CustomSim._renderWorkspaces();

            // 4c. 결합 후 변환 이벤트 바인딩
            CustomSim._bindCombinePost();

            // 5. 저장 모달 이벤트 (프리셋 영역 폐기됨)
            CustomSim._bindSaveModal();
            CustomSim._bindSavedToggle();

            // 6. 동행복권 즉시 로딩 (S2 — 우선순위 ★★★★★)
            await CustomSim.loadDraws('korea');

            // 7. 해외 로또 목록 로딩 + 드롭다운 채우기
            await CustomSim._loadLotteriesAndPopulate();

            // 8. 저장된 필터 목록 로드 (S8)
            await CustomSim._loadSavedFilters();

            // 9. Sweep 이벤트 바인딩 (Stage 6-F-X Phase 5)
            CustomSim._bindSweepEvents();

            console.log('[CustomSim v5-multi] 초기화 완료');
        } catch (e) {
            console.error('[CustomSim v5-multi] Init Error:', e);
        }
    },

    // ── 백워드 호환 게터 (기존 코드가 workspace/transforms 직접 접근) ──
    get workspace() {
        return this.workspaces[0]?.cards || [];
    },
    set workspace(val) {
        if (this.workspaces[0]) this.workspaces[0].cards = val;
    },
    get transforms() {
        return this.workspaces[0]?.transforms || [];
    },
    set transforms(val) {
        if (this.workspaces[0]) this.workspaces[0].transforms = val;
    },

    // ============================================================
    // S8 — 프리셋 라이브러리 (10종)
    // ============================================================

    PRESETS: [
        {
            name: '끝수 합산',
            desc: '1구 끝 + 2구 끝',
            steps: [
                { type: 'main', round: 1, position: 1, tail: true },
                { type: 'op', value: '+' },
                { type: 'main', round: 1, position: 2, tail: true },
            ],
        },
        {
            name: '회차 자릿합',
            desc: '드로우.자릿합',
            steps: [{ type: 'draw', attr: 'digitSum' }],
        },
        {
            name: '양극합',
            desc: '1구 + 6구',
            steps: [
                { type: 'main', round: 1, position: 1, tail: false },
                { type: 'op', value: '+' },
                { type: 'main', round: 1, position: 6, tail: false },
            ],
        },
        {
            name: '끝수 × 10',
            desc: '6구 끝 × 10',
            steps: [
                { type: 'main', round: 1, position: 6, tail: true },
                { type: 'op', value: '*' },
                { type: 'const', value: 10 },
            ],
        },
        {
            name: '보너스 추적',
            desc: '1회차전 보너스 + 2회차전 보너스',
            steps: [
                { type: 'bonus', round: 1, tail: false },
                { type: 'op', value: '+' },
                { type: 'bonus', round: 2, tail: false },
            ],
        },
        {
            name: '추첨일 끝수',
            desc: '1회차전 일.끝',
            steps: [{ type: 'date', round: 1, attr: 'day', tail: true }],
        },
        {
            name: '연산점프',
            desc: '1회차전 1구 + 2회차전 2구 + 3회차전 3구',
            steps: [
                { type: 'main', round: 1, position: 1, tail: false },
                { type: 'op', value: '+' },
                { type: 'main', round: 2, position: 2, tail: false },
                { type: 'op', value: '+' },
                { type: 'main', round: 3, position: 3, tail: false },
            ],
        },
        {
            name: '전라인 +1',
            desc: '1회차전 전라인 + 1',
            steps: [
                { type: 'all_main', round: 1, tail: false },
                { type: 'op', value: '+' },
                { type: 'const', value: 1 },
            ],
        },
        {
            name: '전라인+보너스 −1',
            desc: '1회차전 전라인+보너스 - 1',
            steps: [
                { type: 'all_main_bonus', round: 1, tail: false },
                { type: 'op', value: '-' },
                { type: 'const', value: 1 },
            ],
        },
        {
            name: '전라인 끝수',
            desc: '1회차전 전라인.끝',
            steps: [{ type: 'all_main', round: 1, tail: true }],
        },
    ],

    _renderPresets: () => {
        const el = document.getElementById('preset-area');
        if (!el) return;
        el.innerHTML = CustomSim.PRESETS.map((p, i) =>
            `<button class="preset-chip" data-idx="${i}" title="${p.desc}">${p.name}</button>`
        ).join('');
        el.querySelectorAll('.preset-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                const i = parseInt(btn.dataset.idx);
                CustomSim.formulaSteps = JSON.parse(JSON.stringify(CustomSim.PRESETS[i].steps));
                CustomSim._renderBuilder();
            });
        });
    },

    // ============================================================
    // S8 — 저장된 필터 목록 (수동 + 커스텀)
    // ============================================================

    _loadSavedFilters: async () => {
        const el = document.getElementById('saved-filters-area');
        if (!el) return;
        try {
            // 커스텀필터: ai_custom_analyses.rules.formula = 'simulator_custom'
            const [customRes, manualRes] = await Promise.all([
                window.supabaseClient
                    .from('ai_custom_analyses')
                    .select('id, title, target_numbers, rules, filter_config, created_at')
                    .order('created_at', { ascending: false })
                    .limit(200),
                window.supabaseClient
                    .from('manual_filters')
                    .select('id, title, selected_numbers, source, formula_steps, created_at')
                    .order('created_at', { ascending: false })
                    .limit(200),
            ]);

            const customs = (customRes.data || []).filter(d => d.rules?.formula === 'simulator_custom');
            const manuals = (manualRes.data || []).filter(d => d.source === 'custom_simulator');

            const all = [
                ...customs.map(d => ({ ...d, _type: 'custom' })),
                ...manuals.map(d => ({ ...d, _type: 'manual' })),
            ].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            // [Mod] 이전: slice(0, 8) 8개 고정 → 전체 표시 + 스크롤 컨테이너로 처리

            // 카운트 배지 갱신
            const countBadge = document.getElementById('saved-count-badge');
            if (countBadge) countBadge.textContent = `(${all.length})`;

            if (all.length === 0) {
                el.innerHTML = '<div class="text-sm text-slate-400 italic py-3">저장된 필터가 없습니다. 수식을 만들고 저장 버튼을 눌러보세요.</div>';
                return;
            }

            // [fix-290] all[]을 모듈 캐시로 보관 → 드래그 드롭 시 lookup 가능
            CustomSim._savedFiltersCache = all;

            el.innerHTML = all.map(f => {
                const isCustom = f._type === 'custom';
                const dateStr = f.created_at ? new Date(f.created_at).toISOString().slice(0, 10) : '';
                // 타겟 번호 추출 (드래그 시 즉시 사용)
                const nums = isCustom
                    ? (f.target_numbers || [])
                    : (f.selected_numbers || []);
                const numCount = (nums || []).length;
                return `
                    <div class="saved-row" data-id="${f.id}" data-type="${f._type}"
                         draggable="true"
                         data-drag-type="saved"
                         data-saved-id="${f.id}"
                         data-saved-type="${f._type}"
                         data-saved-title="${(f.title || '').replace(/"/g, '&quot;')}"
                         title="클릭: 빌더에 로드 · 드래그: 워크스페이스로 (${numCount}개 번호)">
                        <div class="flex-1 min-w-0">
                            <div class="saved-name truncate">${f.title || '(제목 없음)'}</div>
                            <div class="saved-meta">${dateStr} · ${numCount}개</div>
                        </div>
                        <span class="saved-type ${isCustom ? 'saved-type-custom' : 'saved-type-manual'}">
                            ${isCustom ? '커스텀' : '수동'}
                        </span>
                    </div>
                `;
            }).join('');

            // [fix-290] 드래그 시작 핸들러 등록
            el.querySelectorAll('.saved-row[draggable="true"]').forEach(row => {
                row.addEventListener('dragstart', (e) => {
                    e.dataTransfer.setData('drag-type', 'saved');
                    e.dataTransfer.setData('drag-saved-id', row.dataset.savedId);
                    e.dataTransfer.setData('drag-saved-type', row.dataset.savedType);
                    e.dataTransfer.setData('drag-saved-title', row.dataset.savedTitle || '');
                    e.dataTransfer.effectAllowed = 'copy';
                });
            });

            // 저장된 필터 클릭 → 워크스페이스에 로드 (v5-multi + v4 레거시 동시 지원)
            el.querySelectorAll('.saved-row').forEach(row => {
                row.addEventListener('click', () => {
                    const id = row.dataset.id;
                    const type = row.dataset.type;
                    const item = all.find(x => x.id === id);
                    if (!item) return;
                    let steps = null;
                    if (type === 'custom') {
                        steps = item.rules?.formula_steps || null;
                    } else {
                        steps = item.formula_steps || null;
                    }
                    if (!steps) {
                        alert('이 필터는 시뮬레이터 빌더로 복원할 데이터가 없습니다.');
                        return;
                    }
                    // v5-multi 객체 — workspaces / combineOps / pattern 복원
                    if (!Array.isArray(steps) && steps.workspaces) {
                        CustomSim.workspaces = JSON.parse(JSON.stringify(steps.workspaces));
                        CustomSim.combineOps = JSON.parse(JSON.stringify(steps.combineOps || []));
                        CustomSim.patternDetected = steps.pattern ? JSON.parse(JSON.stringify(steps.pattern)) : null;
                        CustomSim.activeWsId = CustomSim.workspaces[0]?.id || 'ws-1';
                        CustomSim.formulaSteps = JSON.parse(JSON.stringify(steps));
                        CustomSim._renderWorkspaces();
                        if (typeof CustomSim.refreshPreview === 'function') CustomSim.refreshPreview();
                        return;
                    }
                    // v4 레거시 배열 형식 — 현재 v5 빌더로 복원 불가 안내
                    if (Array.isArray(steps)) {
                        alert('이 필터는 v4 레거시 형식이라 v5 빌더로 자동 복원되지 않습니다.\n수식 정보:\n' + (item.rules?.formula_text || item.formula_text || '(없음)'));
                        return;
                    }
                    alert('이 필터는 시뮬레이터 빌더로 복원할 수 없습니다.');
                });
            });
        } catch (e) {
            console.warn('[CustomSim] 저장된 필터 로드 실패:', e.message);
            el.innerHTML = '<div class="text-sm text-rose-400 italic py-3">로드 실패</div>';
        }
    },

    // ============================================================
    // S9 — 저장 모달 (수동/커스텀 분기)
    // ============================================================

    _selectedSaveType: 'custom',  // 기본 커스텀

    /**
     * 저장된 시뮬레이터 필터 패널 접기/펼치기 토글
     * 상태는 localStorage에 보존 (재방문 시 유지)
     */
    _bindSavedToggle: () => {
        const btn = document.getElementById('btn-toggle-saved');
        const wrapper = document.getElementById('saved-filters-wrapper');
        const icon = document.getElementById('saved-toggle-icon');
        if (!btn || !wrapper || !icon) return;

        const STORAGE_KEY = 'customSim_savedCollapsed';
        const initialCollapsed = localStorage.getItem(STORAGE_KEY) === '1';

        const apply = (collapsed) => {
            if (collapsed) {
                wrapper.style.maxHeight = '0px';
                wrapper.style.opacity = '0';
                icon.style.transform = 'rotate(-90deg)';
            } else {
                wrapper.style.maxHeight = '600px';
                wrapper.style.opacity = '1';
                icon.style.transform = 'rotate(0deg)';
            }
        };

        apply(initialCollapsed);

        btn.addEventListener('click', () => {
            const isCollapsed = wrapper.style.maxHeight === '0px';
            const next = !isCollapsed;
            apply(next);
            localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
        });
    },

    _bindSaveModal: () => {
        const openBtn = document.getElementById('btn-save');
        const modal = document.getElementById('save-modal');
        const closeBtn = document.getElementById('modal-close');
        const cancelBtn = document.getElementById('modal-cancel');
        const submitBtn = document.getElementById('modal-submit');
        const refreshBtn = document.getElementById('btn-refresh-saved');
        if (!openBtn || !modal) return;

        openBtn.addEventListener('click', () => {
            // v5-multi — workspaces 검사 (최소 1개 ws에 카드 있어야 함)
            const hasCards = CustomSim.workspaces.some(ws => ws.cards.length > 0);
            if (!hasCards) {
                alert('먼저 좌측에서 회차/번호를 작업공간으로 드래그하세요.');
                return;
            }
            // workspace + transforms를 formula_steps로 직렬화 (저장용)
            CustomSim.formulaSteps = {
                workspaces: JSON.parse(JSON.stringify(CustomSim.workspaces)),
                combineOps: JSON.parse(JSON.stringify(CustomSim.combineOps)),
                pattern: CustomSim.patternDetected ? JSON.parse(JSON.stringify(CustomSim.patternDetected)) : null,
                version: 'v5-multi',
            };
            // [신규] 제목 자동 생성 — _buildHumanFormula 사용
            // 모달 열 때마다 항상 현재 워크스페이스 수식으로 갱신 (이전 값 무시)
            // → 사용자가 워크스페이스를 수정한 뒤 다시 저장 모달을 열면 새 수식 제목이 표시됨
            // → 사용자가 자동 채워진 제목을 직접 수정하고 저장하면 그 수정값이 저장됨
            const titleInput = document.getElementById('modal-title');
            if (titleInput) {
                const autoTitle = CustomSim._buildHumanFormula(CustomSim.formulaSteps);
                // 너무 길면 50자 이내로 자름 (DB title은 varchar — 안전 길이)
                titleInput.value = autoTitle.length > 50 ? autoTitle.slice(0, 47) + '…' : autoTitle;
            }
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            // 자동 채워진 텍스트 전체 선택 → 사용자가 한번에 덮어쓰기 가능
            titleInput?.focus();
            titleInput?.select();
        });

        const close = () => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        };
        closeBtn?.addEventListener('click', close);
        cancelBtn?.addEventListener('click', close);
        modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

        // 저장 형태 선택
        ['type-custom', 'type-manual'].forEach(id => {
            const card = document.getElementById(id);
            card?.addEventListener('click', () => {
                document.getElementById('type-custom').classList.remove('selected');
                document.getElementById('type-manual').classList.remove('selected');
                card.classList.add('selected');
                CustomSim._selectedSaveType = card.dataset.type;
            });
        });

        // 저장 액션
        submitBtn?.addEventListener('click', async () => {
            await CustomSim._submitSave(close);
        });

        refreshBtn?.addEventListener('click', () => CustomSim._loadSavedFilters());
    },

    /**
     * v5-multi formulaSteps → 사람이 읽을 수 있는 자연어 수식 텍스트
     *
     * 예: "1222회 전라인 + 1220회 1라인 (변환: +0, +1, −1) [끝수expand]"
     *     "W1[1222회 전라인] ∪ W2[1220회 보너스 (변환: +0, +1, −1)]"
     */
    _buildHumanFormula: (steps) => {
        if (!steps || !steps.workspaces || steps.workspaces.length === 0) return '(빈 수식)';

        // 카드 라벨 (회차 정보 제외) — 같은 D-N에 묶이는 카드들의 종류만 표기
        const cardLabel = (c) => {
            if (c.type === 'tail') return `끝수${c.tailNum}풀`;
            if (c.type === 'line') return '전라인';
            if (c.type === 'pos') return `${c.position}라인`;
            if (c.type === 'bonus') return '보너스';
            if (c.type === 'num') return `번호${c.num}`;
            if (c.type === 'round') {
                const dm = c.digitMode || 'thousands';
                if (dm === 'ones') return '회차일';
                if (dm === 'tens') return '회차십';
                if (dm === 'hundreds') return '회차백';
                return '회차값';  // thousands = 전체
            }
            if (c.type === 'date') {
                return ({ year: '년', month: '월', day: '일' }[c.datePart] || '일');
            }
            // [fix-290] 저장된 필터 라벨
            if (c.type === 'saved') {
                return `저장:${c.savedTitle}`;
            }
            // [fix-267] regref 라벨
            if (c.type === 'regref') {
                const sourceWs = (steps.workspaces || []).find(w => w.id === c.sourceWsId);
                const sLabel = sourceWs ? sourceWs.label : '?';
                const refMap = {
                    line: '전라인', bonus: '보너스', all_main_bonus: '전라인+보너스',
                    pos: `${c.position}라인`,
                    round: ({ ones: '회차일', tens: '회차십', hundreds: '회차백', thousands: '회차값' }[c.digitMode] || '회차값'),
                };
                return `회귀@${sLabel}→${refMap[c.refType] || c.refType}`;
            }
            return c.type;
        };

        // 변환 1개 → 자연어
        const txText = (t) => {
            const sym = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': 'mod' }[t.op] || t.op;
            const label = (t.op === '%' && t.value == 10) ? '끝수' : `${sym}${t.value}`;
            return label;
        };

        // 모드 → 한글
        const modeLabel = (mode) => ({
            auto: '', set: '집합', scalar: '합계', tail: '끝수expand'
        }[mode] || '');

        // 결합 op → 기호
        const opSym = (op) => ({
            '+': '+', '-': '−', '*': '×', '/': '÷', '%': '%',
            'union': '∪', 'intersection': '∩', 'complement': '∁',
            'difference': '\\', 'symdiff': '△'
        }[op] || op);

        // 워크스페이스 1개 → 자연어
        // 같은 회차(=같은 offset)의 카드들을 [D-N: 카드1+카드2+…] 로 묶어 표시
        const wsToText = (ws) => {
            // offset별 카드 그룹화 (tail은 회차 무관 별도)
            const groups = new Map();   // key: offset 또는 'tail', value: 카드 라벨 배열
            const order = [];           // 등장 순서 보존
            for (const c of ws.cards || []) {
                let key;
                if (c.type === 'tail') key = 'tail';
                else if (c.type === 'regref') key = `regref-${c.sourceWsId}`;  // [fix-267] 회귀@WS는 offset 없음
                else if (c.type === 'saved') key = `saved-${c.savedId}`;       // [fix-290] 저장 필터
                else key = `D-${c.offset != null ? c.offset : 0}`;  // D-1 = 직전 회차, D-0 = 현재(simNow)
                if (!groups.has(key)) { groups.set(key, []); order.push(key); }
                groups.get(key).push(cardLabel(c));
            }
            // 각 그룹: 카드 1개면 "D-N 라벨", 여러개면 "D-N[라벨1+라벨2+…]"
            const groupTexts = order.map(key => {
                const labels = groups.get(key);
                if (key === 'tail') return labels.join('+');
                if (key.startsWith('regref-')) return labels.join('+');  // [fix-267] regref 라벨 자체에 W1 정보 포함
                if (key.startsWith('saved-')) return labels.join('+');   // [fix-290] saved 라벨 자체에 필터명 포함
                if (labels.length === 1) return `${key} ${labels[0]}`;
                return `${key}[${labels.join('+')}]`;
            });
            const cardsPart = groupTexts.join(' + ') || '(빈)';
            const txs = (ws.transforms || []).map(txText).join(',');
            const txPart = txs ? `(${txs})` : '';
            const ml = modeLabel(ws.mode);
            const modePart = ml ? `[${ml}]` : '';
            return `${cardsPart}${txPart}${modePart}`;
        };

        const wsTexts = steps.workspaces.map(wsToText);
        if (wsTexts.length === 1) return wsTexts[0];

        // 다중 ws → ws 결합 op로 join (W1/W2 라벨 생략, 결합 식만 표시)
        let joined = wsTexts[0];
        for (let i = 1; i < wsTexts.length; i++) {
            const op = (steps.combineOps || [])[i - 1]?.op || 'union';
            joined += ` ${opSym(op)} ${wsTexts[i]}`;
        }
        return joined;
    },

    /**
     * 저장 실행 — 분기 처리:
     *   custom → ai_custom_analyses + simulator_custom formula
     *   manual → manual_filters
     */
    _submitSave: async (closeFn) => {
        const title = document.getElementById('modal-title').value.trim();
        const minM = parseInt(document.getElementById('modal-min').value || '1');
        const maxM = parseInt(document.getElementById('modal-max').value || '6');
        const notes = document.getElementById('modal-notes').value.trim();
        const saveType = CustomSim._selectedSaveType;

        if (!title) { alert('필터명을 입력하세요.'); return; }

        // formulaSteps 검증 — v5-multi(객체) / 레거시 v4(배열) 둘 다 지원
        const fs = CustomSim.formulaSteps;
        const hasV5Cards = fs && !Array.isArray(fs) && fs.workspaces?.some(ws => ws.cards?.length > 0);
        const hasV4Tokens = Array.isArray(fs) && fs.length > 0;
        if (!hasV5Cards && !hasV4Tokens) {
            alert('수식 미정의 — 좌측에서 카드를 드래그한 후 다시 시도하세요.');
            return;
        }

        // 미추첨(다음 회차) 산출 결과 → target_numbers
        // 한국 로또에서 simNow 산출 (사용 가능한 경우 우선), 그 외 인덱스 0
        const isKoreaForSave = CustomSim.currentDB === 'korea' && CustomSim.draws.length > 0;
        const ev0 = isKoreaForSave ? CustomSim.evaluateAt(-1) : CustomSim.evaluateAt(0);
        const targetNumbers = ev0.normalizedSet || [];

        // formula_text 빌드 — 버전별 분기 (사람이 읽을 수 있는 자연어 형식)
        let formulaText;
        if (hasV5Cards) {
            formulaText = CustomSim._buildHumanFormula(fs);
        } else {
            formulaText = fs.map(t => CustomSim._tokenText(t)).join(' ');
        }
        const dbId = CustomSim.currentDB;
        const stepsClone = JSON.parse(JSON.stringify(fs));

        try {
            CustomSim.showLoading(true);

            if (saveType === 'custom') {
                // ── 커스텀필터 → ai_custom_analyses ────────────────────────
                // 마스터 행으로 저장 (target_round=null). 필터페이지/대시보드가 마스터 행만 조회.
                // 회차별 simNow 산출은 evalSimulatorFormulaForDraw + analysis.target_numbers fallback으로 동적 처리.
                const _userId = window.filterService?.userId || null;
                const promptText = `${title} — ${formulaText}${notes ? ' / ' + notes : ''}`;
                // [fix-264] insert 후 id 회수 → lnbOrder 끝에 append (대시보드/LNB 모두 끝으로 정렬됨)
                const { data: inserted, error } = await window.supabaseClient
                    .from('ai_custom_analyses')
                    .insert({
                        title,
                        type: 'dynamic',
                        prompt: promptText,                   // ★ NOT NULL 컬럼
                        target_numbers: targetNumbers,        // simNow 산출 결과 (마스터 기본값)
                        target_round: null,                   // ★ 마스터 행 — 필터페이지 조회 호환
                        rules: {
                            formula: 'simulator_custom',     // 식별자
                            formula_text: formulaText,
                            formula_steps: stepsClone,
                            db_id: dbId,
                            window_n: CustomSim.windowN,
                        },
                        filter_config: { min: minM, max: maxM, enabled: true },
                        description: notes || `시뮬레이터 자동 생성 — ${formulaText}`,
                        user_id: _userId,
                    })
                    .select('id')
                    .single();
                if (error) throw error;

                // [fix-293] lnbOrder append 제거 — 부분 lnbOrder가 있을 때 신규 필터가 중간에 끼어드는 문제 해결
                // 정렬 로직이 자동 처리:
                //   1. lnbOrder 안 항목 → 명시 순서대로 먼저 (사용자 reorder 의도 보존)
                //   2. lnbOrder 밖 항목 (신규 + 미등록 필터들) → DB created_at ASC 순서 (신규 = 가장 늦은 시각 = 마지막)
                // → append를 안 하면 신규 필터는 자동으로 lnbOrder 밖에 위치 → 정확히 맨 끝에 노출됨
                try {
                    const _orderUid = _userId
                        || (await window.supabaseClient.auth.getUser()).data?.user?.id
                        || localStorage.getItem('_lastLoginUserId')
                        || null;
                    const _orderKey = _orderUid ? `lnbOrder_custom_${_orderUid}` : 'lnbOrder_custom_guest';
                    // 다른 탭/페이지에 storage 이벤트만 알림 (lnbOrder 자체는 건드리지 않음)
                    try { window.dispatchEvent(new StorageEvent('storage', { key: _orderKey, newValue: localStorage.getItem(_orderKey) })); } catch (_) { }
                } catch (orderErr) {
                    console.warn('[CustomSim] storage 이벤트 알림 실패 (무시):', orderErr);
                }

                alert('커스텀필터로 저장되었습니다.\n분석/검증/대시보드에 자동 반영됩니다.');
            } else {
                // ── 수동필터 → manual_filters ─────────────────────────────
                const _userId = window.filterService?.userId || null;
                const targetRound = (CustomSim.draws[0]?.drawNo || 0) + 1;
                const { error } = await window.supabaseClient
                    .from('manual_filters')
                    .insert({
                        title,
                        selected_numbers: targetNumbers,
                        min_match: minM,
                        max_match: maxM,
                        target_round: targetRound,
                        preserve: false,
                        notes,
                        // 시뮬레이터 메타 (재실행 가능)
                        source: 'custom_simulator',
                        formula_steps: stepsClone,
                        formula_text: formulaText,
                        user_id: _userId,
                    });
                if (error) throw error;
                alert('수동필터로 저장되었습니다.');
            }

            // 닫기 + 목록 새로고침
            closeFn();
            await CustomSim._loadSavedFilters();
        } catch (e) {
            console.error('[CustomSim] 저장 실패:', e);
            alert('저장 실패: ' + (e.message || '알 수 없는 오류'));
        } finally {
            CustomSim.showLoading(false);
        }
    },

    // ============================================================
    // v5 — 드래그앤드롭 작업 공간 + 패턴 자동 감지
    // ============================================================

    _bindWorkspace: () => {
        // v5-multi: 정적 #ws-dropzone 제거됨 — 모든 ws-dropzone은 동적 렌더
        // 이벤트 위임으로 처리 (early-return 금지)
        const modeLine = document.getElementById('ws-mode-line');
        const modeNum = document.getElementById('ws-mode-num');
        const patApplyBtn = document.getElementById('ws-pattern-apply');
        const patSkipBtn = document.getElementById('ws-pattern-skip');

        // ── Drop zone (이벤트 위임 — 각 ws-dropzone이 wsId를 data-ws-id에 가짐) ──
        // NOTE: 실제 drop zone은 동적 렌더되므로 document에 위임
        document.addEventListener('dragover', (e) => {
            const dz = e.target.closest('.ws-dropzone');
            if (!dz) return;
            e.preventDefault();
            dz.classList.add('drop-active');
        });
        document.addEventListener('dragleave', (e) => {
            const dz = e.target.closest('.ws-dropzone');
            if (dz) dz.classList.remove('drop-active');
        });
        document.addEventListener('drop', (e) => {
            const dz = e.target.closest('.ws-dropzone');
            if (!dz) return;
            e.preventDefault();
            dz.classList.remove('drop-active');
            const wsId = dz.dataset.wsId;
            const type = e.dataTransfer.getData('drag-type');

            // [fix-290] 저장된 필터 드롭 처리
            if (type === 'saved') {
                const savedId = e.dataTransfer.getData('drag-saved-id');
                const savedType = e.dataTransfer.getData('drag-saved-type');
                CustomSim._addSavedFilterToWorkspace(wsId, savedId, savedType);
                return;
            }

            const roundKey = e.dataTransfer.getData('drag-round');
            const num = e.dataTransfer.getData('drag-num');
            const pos = e.dataTransfer.getData('drag-pos');
            const datePart = e.dataTransfer.getData('drag-date-part');
            const digitMode = e.dataTransfer.getData('drag-digit-mode');
            CustomSim._addToWorkspace(
                wsId,
                type,
                roundKey,
                num ? parseInt(num) : null,
                pos ? parseInt(pos) : null,
                datePart || null,
                digitMode || null
            );

            // 끝수 표시 모드에서 드롭 시 자동으로 워크스페이스 mode='tail' 활성화
            if (CustomSim.dataMode === 'tails') {
                const ws = CustomSim.workspaces.find(w => w.id === wsId);
                if (ws && ws.mode !== 'tail') {
                    ws.mode = 'tail';
                    CustomSim._renderWorkspaces();
                    CustomSim.refreshPreview();
                }
            }
        });

        // 좌측 회차 chip drag start (이벤트 위임)
        document.getElementById('draws-list')?.addEventListener('dragstart', (e) => {
            const el = e.target.closest('[draggable="true"]');
            if (!el) return;
            e.dataTransfer.setData('drag-type', el.dataset.dragType || '');
            e.dataTransfer.setData('drag-round', el.dataset.dragRound || '');
            e.dataTransfer.setData('drag-num', el.dataset.dragNum || '');
            e.dataTransfer.setData('drag-pos', el.dataset.dragPos || '');
            e.dataTransfer.setData('drag-date-part', el.dataset.dragDatePart || '');
            // 회차 자릿수 모드 (ones/tens/hundreds/thousands)
            e.dataTransfer.setData('drag-digit-mode', el.dataset.dragDigitMode || '');
            // drag-tail 폐기 (끝수 0~9 패널 제거됨, dataMode='tails'는 표시 모드만)
            e.dataTransfer.effectAllowed = 'copy';
        });

        // [신규] 좌측 chip 더블클릭 → 마지막 워크스페이스에 즉시 추가 (드래그앤드롭 단축키)
        // [fix-263] 더블클릭 임계 200ms → 350ms (반응 폭 확대) + native dblclick 이벤트도 함께 listen
        // [fix-265] click 수동 추적과 native dblclick 중복 → _lastAddAt 타임스탬프로 600ms 락 (이중 등록 방지)
        let _dblClickTarget = null, _dblClickTimer = null;
        let _lastAddAt = 0;        // 마지막으로 카드 추가한 시각 (ms) — 두 핸들러 공유
        const DBL_THRESHOLD = 350; // 두 번째 클릭 허용 윈도우 (ms)
        const ADD_LOCK_MS = 600;   // 추가 후 다른 핸들러 중복 차단 시간 (ms)
        document.getElementById('draws-list')?.addEventListener('click', (e) => {
            const el = e.target.closest('[draggable="true"]');
            if (!el) return;

            if (_dblClickTimer && _dblClickTarget === el) {
                // ── threshold 이내 2번 클릭 → 더블클릭 처리
                clearTimeout(_dblClickTimer);
                _dblClickTimer = null;
                _dblClickTarget = null;
                e.preventDefault();
                // [fix-265] 직전 ADD_LOCK_MS 이내 추가된 적 있으면 skip
                if (Date.now() - _lastAddAt < ADD_LOCK_MS) return;
                const lastWs = CustomSim.workspaces[CustomSim.workspaces.length - 1];
                if (!lastWs) return;
                const type = el.dataset.dragType || '';
                const roundKey = el.dataset.dragRound || '';
                const num = el.dataset.dragNum;
                const pos = el.dataset.dragPos;
                const datePart = el.dataset.dragDatePart;
                const digitMode = el.dataset.dragDigitMode;
                CustomSim._addToWorkspace(
                    lastWs.id,
                    type,
                    roundKey,
                    num ? parseInt(num) : null,
                    pos ? parseInt(pos) : null,
                    datePart || null,
                    digitMode || null
                );
                _lastAddAt = Date.now();   // [fix-265] 락 갱신
                if (CustomSim.dataMode === 'tails' && lastWs.mode !== 'tail') {
                    lastWs.mode = 'tail';
                    CustomSim._renderWorkspaces();
                    CustomSim.refreshPreview();
                }
            } else {
                // ── 첫 번째 클릭 → DBL_THRESHOLD ms 대기
                _dblClickTarget = el;
                clearTimeout(_dblClickTimer);
                _dblClickTimer = setTimeout(() => {
                    _dblClickTimer = null;
                    _dblClickTarget = null;
                }, DBL_THRESHOLD);
            }
        });

        // [fix-263] native dblclick 이벤트도 같이 listen — OS native 더블클릭은 사용자 OS 설정(~500ms) 따라가나 즉시 처리
        document.getElementById('draws-list')?.addEventListener('dblclick', (e) => {
            const el = e.target.closest('[draggable="true"]');
            if (!el) return;
            // [fix-265] 직전 ADD_LOCK_MS 이내 click 핸들러가 이미 추가했다면 skip
            if (Date.now() - _lastAddAt < ADD_LOCK_MS) {
                e.preventDefault();
                return;
            }
            // 커스텀 timer state 초기화 (중복 처리 방지)
            clearTimeout(_dblClickTimer);
            _dblClickTimer = null;
            _dblClickTarget = null;
            e.preventDefault();
            const lastWs = CustomSim.workspaces[CustomSim.workspaces.length - 1];
            if (!lastWs) return;
            const type = el.dataset.dragType || '';
            const roundKey = el.dataset.dragRound || '';
            const num = el.dataset.dragNum;
            const pos = el.dataset.dragPos;
            const datePart = el.dataset.dragDatePart;
            const digitMode = el.dataset.dragDigitMode;
            CustomSim._addToWorkspace(
                lastWs.id, type, roundKey,
                num ? parseInt(num) : null,
                pos ? parseInt(pos) : null,
                datePart || null,
                digitMode || null
            );
            _lastAddAt = Date.now();   // [fix-265] dblclick 경로 락 갱신
            if (CustomSim.dataMode === 'tails' && lastWs.mode !== 'tail') {
                lastWs.mode = 'tail';
                CustomSim._renderWorkspaces();
                CustomSim.refreshPreview();
            }
        });

        // ── 본번호 / 끝수 모드 토글 ─────────────────────────────────
        document.querySelectorAll('.data-mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                CustomSim.dataMode = mode;
                document.querySelectorAll('.data-mode-btn').forEach(b => {
                    b.classList.toggle('data-mode-active', b.dataset.mode === mode);
                });
                // 회귀와 끝수는 독립 직교: 둘 다 동시 사용 가능
                // 예) 2회귀 + 끝수 모드 = 2회 간격 회차들의 본번호를 끝수로 표시
                CustomSim._renderDrawsList();
            });
        });

        // ── 모드 토글 ──────────────────────────────────────────────
        const setMode = (m) => {
            CustomSim.selectionMode = m;
            modeLine?.classList.toggle('bg-indigo-50', m === 'line');
            modeLine?.classList.toggle('text-indigo-600', m === 'line');
            modeLine?.classList.toggle('bg-slate-50', m !== 'line');
            modeLine?.classList.toggle('text-slate-500', m !== 'line');
            modeNum?.classList.toggle('bg-indigo-50', m === 'num');
            modeNum?.classList.toggle('text-indigo-600', m === 'num');
            modeNum?.classList.toggle('bg-slate-50', m !== 'num');
            modeNum?.classList.toggle('text-slate-500', m !== 'num');
            CustomSim._renderDrawsList();  // chip 드래그 가능 여부 갱신
        };
        modeLine?.addEventListener('click', () => setMode('line'));
        modeNum?.addEventListener('click', () => setMode('num'));

        // ── 변환 버튼 (이벤트 위임) ──────────────────────────────────
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.ws-tx-btn[data-op]');
            if (!btn) return;
            const wsId = btn.closest('.ws-block')?.dataset.wsId;
            const op = btn.dataset.op;
            const value = parseInt(btn.dataset.value);
            CustomSim._addTransform(wsId, op, value);
        });
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.ws-tx-add');
            if (!btn) return;
            const block = btn.closest('.ws-block');
            const wsId = block?.dataset.wsId;
            const op = block?.querySelector('.ws-tx-op')?.value || '+';
            const valStr = block?.querySelector('.ws-tx-val')?.value || '';
            const value = parseInt(valStr);
            if (isNaN(value) || value < 0) {
                alert('변환 값에 0 이상의 정수를 입력하세요.');
                return;
            }
            CustomSim._addTransform(wsId, op, value);
            const inp = block?.querySelector('.ws-tx-val');
            if (inp) inp.value = '';
        });
        // [fix-371] Enter 키 입력 시 추가 버튼 자동 트리거 (워크스페이스 변환)
        document.addEventListener('keydown', (e) => {
            const inp = e.target.closest('.ws-tx-val');
            if (!inp || e.key !== 'Enter') return;
            e.preventDefault();
            const block = inp.closest('.ws-block');
            const btn = block?.querySelector('.ws-tx-add');
            if (btn) btn.click();
        });
        // [fix-372] 변환 칩 안 숫자 inline 편집
        document.addEventListener('input', (e) => {
            const inp = e.target.closest('.ws-tx-val-edit');
            if (!inp) return;
            const wsId = inp.dataset.wsId;
            const idx = parseInt(inp.dataset.txI);
            const ws = CustomSim.workspaces.find(w => w.id === wsId);
            if (!ws || !ws.transforms[idx]) return;
            const v = parseInt(inp.value);
            if (!isNaN(v) && v >= 0) {
                ws.transforms[idx].value = v;
                CustomSim.refreshPreview();
            }
        });
        document.addEventListener('keydown', (e) => {
            const inp = e.target.closest('.ws-tx-val-edit');
            if (!inp || e.key !== 'Enter') return;
            e.preventDefault();
            inp.blur();
        });
        // [fix-372] post-combine 칩 안 숫자 inline 편집
        document.addEventListener('input', (e) => {
            const inp = e.target.closest('.ws-post-tx-val-edit');
            if (!inp) return;
            const idx = parseInt(inp.dataset.idx);
            const tx = CustomSim.combinePostTransforms[idx];
            if (!tx) return;
            const v = parseInt(inp.value);
            if (!isNaN(v) && v >= 0) {
                tx.value = v;
                CustomSim.refreshPreview();
            }
        });
        document.addEventListener('keydown', (e) => {
            const inp = e.target.closest('.ws-post-tx-val-edit');
            if (!inp || e.key !== 'Enter') return;
            e.preventDefault();
            inp.blur();
        });

        // ── 집합 연산 버튼 (이벤트 위임) ─────────────────────────────
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.ws-setop-btn');
            if (!btn) return;
            const wsId = btn.dataset.wsId;
            const op = btn.dataset.op;
            CustomSim._computeSetOp(wsId, op);
        });

        // ── 작업공간 초기화 (단일 ws 리셋) ──────────────────────────
        // NOTE: 각 ws-block의 reset 버튼은 이벤트 위임
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.ws-reset');
            if (!btn) return;
            const wsId = btn.closest('.ws-block')?.dataset.wsId;
            const ws = CustomSim.workspaces.find(w => w.id === wsId);
            if (!ws) return;
            ws.cards = [];
            ws.transforms = [];
            CustomSim.patternDetected = null;
            CustomSim._renderWorkspaces();
            CustomSim.refreshPreview();
        });

        // ── 패턴 적용/건너뛰기 ─────────────────────────────────────
        patApplyBtn?.addEventListener('click', () => {
            document.getElementById('ws-pattern-hint')?.classList.add('hidden');
            CustomSim.patternDetected = null;
        });
        patSkipBtn?.addEventListener('click', () => {
            document.getElementById('ws-pattern-hint')?.classList.add('hidden');
            CustomSim.patternDetected = null;
        });

        // ── 회차 데이터 회귀 selector (1~200 옵션 동적 생성) ─────────
        const regSel = document.getElementById('draws-regression');
        if (regSel && regSel.options.length === 0) {
            const frag = document.createDocumentFragment();
            for (let k = 1; k <= 200; k++) {
                const opt = document.createElement('option');
                opt.value = String(k);
                opt.textContent = `${k}회귀`;
                if (k === 1) opt.selected = true;
                frag.appendChild(opt);
            }
            regSel.appendChild(frag);
        }
        regSel?.addEventListener('change', () => {
            CustomSim._renderDrawsList();
        });

        // ── 워크스페이스 추가/전체 초기화 ─────────────────────────────
        document.getElementById('ws-add')?.addEventListener('click', () => {
            CustomSim._addWorkspace();
        });
        document.getElementById('ws-reset-all')?.addEventListener('click', () => {
            if (!confirm('모든 워크스페이스를 초기화하시겠습니까?')) return;
            CustomSim.workspaces = [{
                id: 'ws-1',
                label: 'W1',
                cards: [],
                transforms: [],
                mode: 'auto',
            }];
            CustomSim.activeWsId = 'ws-1';
            CustomSim.combineOps = [];
            CustomSim.combinePostTransforms = [];
            CustomSim.combinePostExpand = false;
            CustomSim.patternDetected = null;
            CustomSim._renderWorkspaces();
            CustomSim.refreshPreview();
        });
    },

    /**
     * 좌측에서 드래그된 항목을 workspace에 추가
     * @param {string} wsId - 워크스페이스 ID (null이면 activeWsId 사용)
     */
    _addToWorkspace: (wsId, type, roundKey, num, position, datePart, digitMode) => {
        if (!wsId) wsId = CustomSim.activeWsId;
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        const isKorea = CustomSim.currentDB === 'korea';
        let draw;
        if (isKorea) {
            const round = parseInt(roundKey);
            draw = CustomSim.draws.find(d => d.drawNo === round);
            // 미추첨 다음 회차(simNow)에 대한 가상 draw — 회차/일자 칩 전용
            if (!draw) {
                const latest = CustomSim.draws[0];
                const simNow = (latest?.drawNo || 0) + 1;
                if (round === simNow && latest) {
                    const nextDate = latest.drawDate ? new Date(latest.drawDate) : null;
                    if (nextDate) nextDate.setDate(nextDate.getDate() + 7);
                    draw = {
                        drawNo: simNow,
                        drawDate: nextDate ? nextDate.toISOString() : null,
                        numbers: [],
                        bonus: null,
                        maxBall: 45,
                        dbId: 'korea',
                        _pending: true,
                    };
                }
            }
        } else {
            // [fix-307] 해외 모드: roundKey가 숫자(매핑된 한국 회차) 또는 'idx-N' 둘 다 지원
            const round = parseInt(roundKey);
            if (!isNaN(round)) {
                draw = CustomSim.draws.find(d => d.drawNo === round);
            }
            // 'idx-N' 레거시(매핑 안 된 해외 row) 지원
            if (!draw && typeof roundKey === 'string' && roundKey.startsWith('idx-')) {
                const idx = parseInt(roundKey.split('-')[1]);
                draw = CustomSim.draws[idx];
            }
            // 해외 모드 simNow placeholder (한국 simNow에 매핑되는 해외 추첨 없을 때)
            if (!draw && !isNaN(round)) {
                const latestKor = CustomSim.koreaDraws?.[0];
                const simNow = (latestKor?.drawNo || 0) + 1;
                if (round === simNow && latestKor) {
                    const nextDate = latestKor.drawDate ? new Date(latestKor.drawDate) : null;
                    if (nextDate) nextDate.setDate(nextDate.getDate() + 7);
                    draw = {
                        drawNo: simNow,
                        drawDate: nextDate ? nextDate.toISOString() : null,
                        numbers: [],
                        bonus: null,
                        maxBall: CustomSim.draws[0]?.maxBall || 45,
                        dbId: CustomSim.currentDB,
                        _pending: true,
                    };
                }
            }
        }
        if (!draw) return;

        // 미추첨 회차에서는 회차/일자 칩만 허용 (라인/포지션/보너스/번호는 거부)
        if (draw._pending && !['round', 'date'].includes(type)) {
            alert('미추첨 회차에서는 "회차" 또는 "일자"만 드래그할 수 있습니다.');
            return;
        }

        // 현재(시뮬레이터의 "지금") = DB 최신 + 1 (다음 미추첨 회차)
        // 예) DB 최신 1222 → 시뮬레이터 현재=1223. 1222 드래그 시 offset=1
        // 검증 시: targetIdx 회차에서 동일 offset 적용 → draws[targetIdx + offset]
        // [fix-306] 해외 로또: drawNo가 korRound로 매핑됨 → 한국 simNow 기준 offset 정상 산출
        const latestInDB = (isKorea
            ? (CustomSim.draws[0]?.drawNo || 0)
            : (CustomSim.koreaDraws?.[0]?.drawNo || CustomSim.draws[0]?.drawNo || 0));
        const simNow = latestInDB + 1;
        // drawNo가 유효(매핑된 한국 회차)면 offset 산출, 아니면 -1 fallback
        const offset = (draw.drawNo != null) ? (simNow - draw.drawNo) : -1;

        const card = {
            type,                                // 'line' | 'pos' | 'num' | 'bonus' | 'round' | 'date' | 'combine'
            roundKey,                            // 표시용
            offset,                              // 일반화용
            drawNo: draw.drawNo,
            drawDate: draw.drawDate,
            numbers: draw.numbers,
            bonus: draw.bonus,
            num: (type === 'num' && num != null) ? num : null,
            position: (type === 'pos' && position != null) ? position : null,
            datePart: (type === 'date') ? (datePart || 'day') : null,  // 'year' | 'month' | 'day'
            digitMode: (type === 'round') ? (digitMode || 'thousands') : null,  // 'ones' | 'tens' | 'hundreds' | 'thousands'
        };
        ws.cards.push(card);
        CustomSim._detectPattern();
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * 끝수 카드를 워크스페이스에 추가 (회차 무관, offset=0)
     */
    _addTailToWorkspace: (wsId, tailNum) => {
        if (!wsId) wsId = CustomSim.activeWsId;
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        if (tailNum == null || isNaN(tailNum) || tailNum < 0 || tailNum > 9) return;
        const card = {
            type: 'tail',
            tailNum,
            roundKey: `tail-${tailNum}`,
            offset: 0,                       // 회차 무관
            drawNo: null,
            drawDate: null,
            numbers: [],
            bonus: null,
            num: null,
            position: null,
            datePart: null,
        };
        ws.cards.push(card);
        CustomSim._detectPattern();
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * Stage 6-5-1: op 토큰을 워크스페이스에 추가
     * 마지막 카드가 chip이면 추가, op이면 무시
     */
    /**
     * [fix-290] 저장된 필터 → 워크스페이스 카드로 추가
     * 드롭 시점의 target_numbers 스냅샷을 카드에 저장 → 평가 시 그대로 사용
     */
    _addSavedFilterToWorkspace: (wsId, savedId, savedType) => {
        if (!wsId) wsId = CustomSim.activeWsId;
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        // 캐시에서 lookup
        const cache = CustomSim._savedFiltersCache || [];
        const filter = cache.find(f => f.id === savedId);
        if (!filter) {
            alert('저장된 필터를 찾을 수 없습니다. 새로고침 후 다시 시도해주세요.');
            return;
        }
        // 타겟 번호 추출
        const isCustom = savedType === 'custom';
        const targetNums = (isCustom ? filter.target_numbers : filter.selected_numbers) || [];
        if (targetNums.length === 0) {
            alert('이 필터는 타겟 번호가 비어있어 워크스페이스에 추가할 수 없습니다.');
            return;
        }
        ws.cards.push({
            type: 'saved',
            savedId,
            savedType,
            savedTitle: filter.title || '(제목 없음)',
            targetNumbers: [...targetNums].sort((a, b) => a - b),
        });
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * [fix-267] 회귀@WS 카드 추가 모달
     * 다른 워크스페이스의 산출값(스칼라 N)을 회귀 offset으로 사용 →
     * draws[targetIdx + N]을 dereferencing 하여 그 회차의 라인/보너스/포지션/회차값 추출
     */
    _openRegrefModal: (wsId) => {
        const targetWs = CustomSim.workspaces.find(w => w.id === wsId);
        if (!targetWs) return;
        // 자기 자신 제외 — 사이클 차단 (런타임에서도 또 검출하지만 UI에서 미리 거름)
        const candidates = CustomSim.workspaces.filter(w => w.id !== wsId);
        if (candidates.length === 0) {
            alert('회귀@WS를 사용하려면 최소 2개의 워크스페이스가 필요합니다.\n상단 ＋ 버튼으로 워크스페이스를 추가하고, 거기에 offset 값(예: 회차십+0)을 만들어 주세요.');
            return;
        }
        // 기존 모달 제거 (중복 방지)
        document.getElementById('regref-modal')?.remove();

        const modal = document.createElement('div');
        modal.id = 'regref-modal';
        modal.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,0.6);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `
            <div style="background:#fff;border-radius:16px;padding:24px 28px;width:min(480px,92vw);box-shadow:0 25px 50px -12px rgba(0,0,0,0.4);">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;">
                    <h3 style="font-size:16px;font-weight:900;color:#0f172a;">회귀@WS 카드 추가</h3>
                    <button id="regref-modal-close" style="color:#94a3b8;font-size:20px;line-height:1;background:none;border:none;cursor:pointer;">✕</button>
                </div>
                <div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:14px;background:#f8fafc;border-radius:8px;padding:10px 12px;">
                    선택한 워크스페이스의 첫 번째 산출값 N을 회귀 offset으로 사용합니다.<br>
                    예) W1 = <code style="background:#fff;padding:1px 4px;border-radius:3px;">회차십(1224)+0=24</code> → <b>24회귀</b> = sorted[targetIdx+24] = 1200회차
                </div>

                <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:6px;">소스 워크스페이스 (offset N)</label>
                <select id="regref-source-ws" style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;margin-bottom:14px;background:#fff;">
                    ${candidates.map(w => `<option value="${w.id}">${w.label} ${w.cards.length === 0 ? '(빈 워크스페이스 — 먼저 카드를 추가해야 함)' : ''}</option>`).join('')}
                </select>

                <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:6px;">추출 타입</label>
                <div id="regref-type-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;">
                    <button class="regref-type-btn" data-type="line" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;font-weight:700;background:#eef2ff;color:#4338ca;cursor:pointer;">전라인</button>
                    <button class="regref-type-btn" data-type="bonus" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;font-weight:700;background:#fef3c7;color:#b45309;cursor:pointer;">보너스</button>
                    <button class="regref-type-btn" data-type="all_main_bonus" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;font-weight:700;background:#fce7f3;color:#be185d;cursor:pointer;">전라인+보너스</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="1" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">1번</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="2" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">2번</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="3" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">3번</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="4" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">4번</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="5" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">5번</button>
                    <button class="regref-type-btn" data-type="pos" data-pos="6" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#475569;cursor:pointer;">6번</button>
                    <button class="regref-type-btn" data-type="round" data-digit="ones" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#92400e;cursor:pointer;">회차일</button>
                    <button class="regref-type-btn" data-type="round" data-digit="tens" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#92400e;cursor:pointer;">회차십</button>
                    <button class="regref-type-btn" data-type="round" data-digit="thousands" style="padding:8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#fff;color:#92400e;cursor:pointer;">회차값</button>
                </div>
                <div style="font-size:11px;color:#94a3b8;margin-top:10px;">버튼 클릭 → 즉시 추가 + 모달 닫힘</div>
            </div>
        `;
        document.body.appendChild(modal);
        document.getElementById('regref-modal-close').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });

        modal.querySelectorAll('.regref-type-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const sourceWsId = document.getElementById('regref-source-ws').value;
                const refType = btn.dataset.type;
                const position = btn.dataset.pos ? parseInt(btn.dataset.pos) : null;
                const digitMode = btn.dataset.digit || null;
                CustomSim._addRegrefCard(wsId, sourceWsId, refType, position, digitMode);
                modal.remove();
            });
        });
    },

    /**
     * [fix-267] regref 카드를 워크스페이스에 추가
     */
    _addRegrefCard: (wsId, sourceWsId, refType, position, digitMode) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        if (sourceWsId === wsId) {
            alert('자기 자신을 회귀 소스로 지정할 수 없습니다.');
            return;
        }
        ws.cards.push({
            type: 'regref',
            sourceWsId,
            refType,
            position: position || null,
            digitMode: digitMode || null,
        });
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    _addOpToWorkspace: (wsId, op) => {
        if (!wsId) wsId = CustomSim.activeWsId;
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        if (ws.cards.length === 0) {
            alert('먼저 좌측에서 회차/번호 chip을 추가하세요.');
            return;
        }
        const lastCard = ws.cards[ws.cards.length - 1];
        if (lastCard.type === 'op') {
            alert('연산자는 chip 다음에만 추가할 수 있습니다.');
            return;
        }
        ws.cards.push({ type: 'op', value: op });
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * Stage 6-5-1: op 토큰 cycle (+ → - → × → ÷ → % → +)
     */
    _cycleOp: (wsId, idx) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws || !ws.cards[idx] || ws.cards[idx].type !== 'op') return;
        const ops = ['+', '-', '*', '/', '%'];
        const cur = ws.cards[idx].value;
        const curIdx = ops.indexOf(cur);
        ws.cards[idx].value = ops[(curIdx + 1) % ops.length];
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * 작업공간에서 카드 제거
     */
    _removeFromWorkspace: (wsId, idx) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        ws.cards.splice(idx, 1);
        CustomSim._detectPattern();
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    _addTransform: (wsId, op, value) => {
        if (!wsId) wsId = CustomSim.activeWsId;
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        if (ws.cards.length === 0) {
            alert('먼저 좌측에서 회차/번호를 드래그하여 추가하세요.');
            return;
        }
        ws.transforms.push({ op, value });
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    _removeTransform: (wsId, idx) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;
        ws.transforms.splice(idx, 1);
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * 패턴 감지 — 등간격 회귀, 가속/감속 등 (활성 ws 기준)
     */
    _detectPattern: () => {
        const hintEl = document.getElementById('ws-pattern-hint');
        const titleEl = document.getElementById('ws-pattern-title');
        const descEl = document.getElementById('ws-pattern-desc');
        if (!hintEl) return;

        const activeWs = CustomSim.workspaces.find(w => w.id === CustomSim.activeWsId);
        if (!activeWs) return;
        // 패턴 감지는 본번호 카드 (line / num) 중심
        const lineCards = activeWs.cards.filter(c => c.type === 'line' || c.type === 'num');
        if (lineCards.length < 2) {
            hintEl.classList.add('hidden');
            CustomSim.patternDetected = null;
            return;
        }
        // 한국 로또 또는 한국 회차로 매핑된 해외 로또에서 회귀 패턴 인식 (offset 사용)
        // [fix-306] 해외도 drawNo=korRound 매핑되면 회귀 패턴 정상 작동
        const hasValidOffsets = lineCards.every(c => c.offset != null && c.offset > 0);
        if (CustomSim.currentDB !== 'korea' && !hasValidOffsets) {
            hintEl.classList.add('hidden');
            return;
        }
        const offsets = lineCards.map(c => c.offset);
        // 인접 차이 계산 (offset 증가 방향)
        const diffs = [];
        for (let i = 1; i < offsets.length; i++) {
            diffs.push(offsets[i] - offsets[i - 1]);
        }
        const allEqual = diffs.length > 0 && diffs.every(d => d === diffs[0]);
        const k = diffs[0];

        if (allEqual && k > 0) {
            CustomSim.patternDetected = { kind: 'regression', step: k, count: lineCards.length };
            titleEl.textContent = `💡 ${k}회귀 등간격 패턴 감지`;
            descEl.textContent = `간격 ${k}회차 — ${lineCards.length}개 회차 (offset: ${offsets.join(', ')}). 모든 회차에 일반화하여 검증합니다.`;
            hintEl.classList.remove('hidden');
        } else if (allEqual && k < 0) {
            CustomSim.patternDetected = null;
            hintEl.classList.add('hidden');
        } else {
            CustomSim.patternDetected = { kind: 'manual', offsets };
            titleEl.textContent = `📌 사용자 정의 패턴`;
            descEl.textContent = `불규칙 간격 (${diffs.join(', ')}) — 드래그한 회차 그대로 사용합니다.`;
            hintEl.classList.remove('hidden');
        }
    },

    /**
     * 다중 워크스페이스 렌더 (v5-multi)
     */
    _renderWorkspaces: () => {
        const container = document.getElementById('ws-container');
        if (!container) return;

        container.innerHTML = CustomSim.workspaces.map((ws, idx) => {
            const modeLabel = { auto: '자동', set: '집합', scalar: '합계', tail: '끝수 expand' }[ws.mode] || ws.mode;

            return `
                <div class="ws-block ${ws.hiddenInOutput ? 'ws-hidden-output' : ''}" data-ws-id="${ws.id}">
                    <div class="ws-block-head">
                        <input class="ws-label-input" value="${ws.label}" data-ws-id="${ws.id}">
                        <span class="ws-mode-toggle text-[11px] text-slate-500 cursor-pointer" data-ws-id="${ws.id}">모드: ${modeLabel}</span>
                        <label class="ws-hidden-toggle text-[11px] text-slate-500 cursor-pointer flex items-center gap-1 ml-2" title="체크 시: 이 워크스페이스는 최종 결합에서 제외됨 (regref 소스 전용)">
                            <input type="checkbox" class="ws-hidden-checkbox" data-ws-id="${ws.id}" ${ws.hiddenInOutput ? 'checked' : ''} style="margin:0;">
                            <span>regref 전용</span>
                        </label>
                        ${CustomSim.workspaces.length > 1 ? `<button class="ws-remove text-slate-400 hover:text-red-600 text-xs ml-auto" data-ws-id="${ws.id}">✕</button>` : ''}
                    </div>
                    <div class="ws-op-row mt-2 mb-3 flex items-center gap-2 flex-wrap">
                        <span class="text-xs text-slate-400 mr-1">연산:</span>
                        <button class="ws-op-add-btn text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 font-bold hover:bg-indigo-100" data-op="+" data-ws-id="${ws.id}">+</button>
                        <button class="ws-op-add-btn text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 font-bold hover:bg-indigo-100" data-op="-" data-ws-id="${ws.id}">−</button>
                        <button class="ws-op-add-btn text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 font-bold hover:bg-indigo-100" data-op="*" data-ws-id="${ws.id}">×</button>
                        <button class="ws-op-add-btn text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 font-bold hover:bg-indigo-100" data-op="/" data-ws-id="${ws.id}">÷</button>
                        <button class="ws-op-add-btn text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 font-bold hover:bg-indigo-100" data-op="%" data-ws-id="${ws.id}">%</button>
                        <span class="text-xs text-slate-300 mx-1">|</span>
                        <button class="ws-regref-btn text-xs px-3 py-1 rounded bg-teal-50 text-teal-700 font-bold hover:bg-teal-100" data-ws-id="${ws.id}" title="다른 워크스페이스 산출값을 회귀 offset으로 사용 → 그 회차의 라인/보너스/포지션 추출">
                            회귀@WS
                        </button>
                    </div>
                    <div class="ws-dropzone" data-ws-id="${ws.id}">
                        ${ws.cards.length === 0
                            ? '<div class="ws-empty-hint text-xs text-slate-400 italic text-center py-4">좌측 회차 chip을 드래그</div>'
                            : `<div class="ws-cards flex items-center flex-wrap gap-2">${ws.cards.map((c, i) => CustomSim._renderWorkspaceCard(c, i, ws.id)).join('')}</div>`
                        }
                    </div>
                    <div class="ws-tx-controls mt-3 flex items-center gap-1 flex-wrap">
                        <span class="text-[10px] text-slate-500 mr-1">변환</span>
                        <button class="ws-tx-btn" data-op="+" data-value="0" data-ws-id="${ws.id}">+0</button>
                        <button class="ws-tx-btn" data-op="+" data-value="1" data-ws-id="${ws.id}">+1</button>
                        <button class="ws-tx-btn" data-op="-" data-value="1" data-ws-id="${ws.id}">−1</button>
                        <button class="ws-tx-btn" data-op="+" data-value="2" data-ws-id="${ws.id}">+2</button>
                        <button class="ws-tx-btn" data-op="-" data-value="2" data-ws-id="${ws.id}">−2</button>
                        <button class="ws-tx-btn" data-op="*" data-value="2" data-ws-id="${ws.id}">×2</button>
                        <button class="ws-tx-btn" data-op="/" data-value="2" data-ws-id="${ws.id}">÷2</button>
                        <button class="ws-tx-btn" data-op="*" data-value="3" data-ws-id="${ws.id}">×3</button>
                        <button class="ws-tx-btn" data-op="/" data-value="3" data-ws-id="${ws.id}">÷3</button>
                        <button class="ws-tx-btn" data-op="%" data-value="10" data-ws-id="${ws.id}" title="끝수 (%10) — 번호의 1자리(0~9)">끝수</button>
                        <span class="text-slate-300 mx-1">|</span>
                        <select class="ws-tx-op select-underline text-xs">
                            <option value="+">+</option>
                            <option value="-">−</option>
                            <option value="*">×</option>
                            <option value="/">÷</option>
                            <option value="%">%</option>
                        </select>
                        <input class="ws-tx-val input-underline w-14 text-xs" type="number" placeholder="값" min="0">
                        <button class="ws-tx-add btn-ghost text-[10px] px-2 py-1">
                            <span class="material-symbols-outlined text-[12px]">add</span>추가
                        </button>
                    </div>
                    <div class="ws-tx-chain mt-2 flex items-center gap-2 flex-wrap min-h-[24px]">
                        ${ws.transforms.length === 0
                            ? '<span class="text-[10px] text-slate-300 italic">변환 없음</span>'
                            : ws.transforms.map((t, i) => {
                                // [fix-372] 칩 안 inline 숫자 편집 — 연산자 그대로 + input으로 값 변경
                                const sym = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': 'mod' }[t.op] || t.op;
                                const isTail = (t.op === '%' && t.value == 10);
                                const isVar = t.isVariable || false;
                                const varClass = isVar ? ' ws-var-chip' : '';
                                if (isTail) {
                                    return `<span class="ws-tx-chip${varClass} text-[10px]">끝수<span class="ws-tx-var-toggle" data-tx-var-toggle="${i}" data-ws-id="${ws.id}">$</span><span class="ws-tx-chip-x cursor-pointer ml-1" data-tx-x="${i}" data-ws-id="${ws.id}">✕</span></span>`;
                                }
                                return `<span class="ws-tx-chip${varClass} text-[10px] inline-flex items-center gap-0.5" style="padding:2px 6px">
                                    <span class="font-bold">${sym}</span>
                                    <input type="number" class="ws-tx-val-edit" data-tx-i="${i}" data-ws-id="${ws.id}" value="${isVar ? 'x' : t.value}" style="width:42px;background:transparent;border:none;outline:none;text-align:center;font-size:10px;font-weight:700;color:inherit;padding:0;-moz-appearance:textfield" min="0" ${isVar ? 'disabled' : ''}>
                                    <span class="ws-tx-var-toggle" data-tx-var-toggle="${i}" data-ws-id="${ws.id}">$</span>
                                    <span class="ws-tx-chip-x cursor-pointer" data-tx-x="${i}" data-ws-id="${ws.id}" style="margin-left:2px">✕</span>
                                </span>`;
                            }).join('')
                        }
                    </div>
                    ${ws.cards.filter(c => c.numbers && c.numbers.length > 0).length >= 2 ? `
                    <div class="ws-setop-controls mt-2 flex items-center gap-1 flex-wrap">
                        <span class="text-[10px] text-slate-500 mr-1">집합</span>
                        <button class="ws-setop-btn${(ws.setOpOverride||{}).op==='union'?' ws-setop-btn-active':''}" data-op="union" data-ws-id="${ws.id}">∪ 합집합</button>
                        <button class="ws-setop-btn${(ws.setOpOverride||{}).op==='intersection'?' ws-setop-btn-active':''}" data-op="intersection" data-ws-id="${ws.id}">∩ 교집합</button>
                        <button class="ws-setop-btn${(ws.setOpOverride||{}).op==='difference'?' ws-setop-btn-active':''}" data-op="difference" data-ws-id="${ws.id}">A∖B 차집합</button>
                        <button class="ws-setop-btn${(ws.setOpOverride||{}).op==='complement'?' ws-setop-btn-active':''}" data-op="complement" data-ws-id="${ws.id}">∁ 미포함</button>
                        <button class="ws-setop-btn${(ws.setOpOverride||{}).op==='symdiff'?' ws-setop-btn-active':''}" data-op="symdiff" data-ws-id="${ws.id}">△ 대칭차</button>
                        ${ws.setOpOverride ? `<span class="ws-setop-clear text-[10px] text-red-400 hover:text-red-600 cursor-pointer ml-2 font-bold" data-ws-id="${ws.id}">✕ 해제</span>` : ''}
                    </div>
                    <div class="ws-setop-result mt-1${ws.setOpOverride ? '' : ' hidden'}" data-ws-id="${ws.id}"></div>
                    ` : ''}
                </div>
            `;
        }).join('');

        // 이벤트 바인딩 (위임)
        // 라벨 변경
        container.querySelectorAll('.ws-label-input').forEach(inp => {
            inp.addEventListener('change', (e) => {
                const wsId = e.target.dataset.wsId;
                const ws = CustomSim.workspaces.find(w => w.id === wsId);
                if (ws) ws.label = e.target.value;
            });
        });
        // (활성/비활성 토글 제거됨 - 모든 ws가 평가에 동일하게 포함됨)
        // 워크스페이스 제거
        container.querySelectorAll('.ws-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const wsId = e.target.dataset.wsId;
                CustomSim._removeWorkspace(wsId);
            });
        });
        // Stage 6-5-1: op 버튼 클릭 — 마지막 카드가 chip이면 op 토큰 추가
        container.querySelectorAll('.ws-op-add-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const wsId = e.target.dataset.wsId;
                const op = e.target.dataset.op;
                CustomSim._addOpToWorkspace(wsId, op);
            });
        });
        // [fix-267] 회귀@WS 버튼 클릭 → 모달 오픈 (소스 WS + 추출 타입 선택)
        container.querySelectorAll('.ws-regref-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const wsId = e.target.dataset.wsId || e.currentTarget.dataset.wsId;
                CustomSim._openRegrefModal(wsId);
            });
        });
        // [fix-267] regref 전용 토글 (hiddenInOutput)
        container.querySelectorAll('.ws-hidden-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const wsId = e.target.dataset.wsId;
                const ws = CustomSim.workspaces.find(w => w.id === wsId);
                if (ws) {
                    ws.hiddenInOutput = e.target.checked;
                    CustomSim._renderWorkspaces();
                    CustomSim.refreshPreview();
                }
            });
        });
        // 카드 제거 (op 토큰 포함)
        container.querySelectorAll('[data-ws-x]').forEach(el => {
            el.addEventListener('click', (e) => {
                const wsId = el.dataset.wsId;
                const idx = parseInt(el.dataset.wsX);
                CustomSim._removeFromWorkspace(wsId, idx);
            });
        });
        // Stage 6-5-1: op badge 클릭 → op cycle (+ → - → × → ÷ → % → +)
        container.querySelectorAll('.ws-op-badge').forEach(badge => {
            badge.addEventListener('click', (e) => {
                if (e.target.classList.contains('ws-op-badge-x')) return; // x 버튼은 제거 처리
                const wsId = badge.dataset.wsId;
                const idx = parseInt(badge.dataset.wsX);
                CustomSim._cycleOp(wsId, idx);
            });
        });
        // 변환 제거
        container.querySelectorAll('[data-tx-x]').forEach(el => {
            el.addEventListener('click', (e) => {
                const wsId = el.dataset.wsId;
                const idx = parseInt(el.dataset.txX);
                CustomSim._removeTransform(wsId, idx);
            });
        });
        // 모드 토글
        container.querySelectorAll('.ws-mode-toggle').forEach(el => {
            el.addEventListener('click', (e) => {
                const wsId = e.target.dataset.wsId;
                const ws = CustomSim.workspaces.find(w => w.id === wsId);
                if (!ws) return;
                const modes = ['auto', 'set', 'scalar', 'tail'];
                const curIdx = modes.indexOf(ws.mode);
                ws.mode = modes[(curIdx + 1) % modes.length];
                CustomSim._renderWorkspaces();
                CustomSim.refreshPreview();
            });
        });

        // Stage 6-F-X: 변수 토글 ($)
        container.querySelectorAll('.ws-tx-var-toggle').forEach(el => {
            el.addEventListener('click', (e) => {
                const wsId = el.dataset.wsId;
                const idx = parseInt(el.dataset.txVarToggle);
                CustomSim._onVarToggle(wsId, idx);
            });
        });

        // 집합 연산 해제 버튼
        container.querySelectorAll('.ws-setop-clear').forEach(el => {
            el.addEventListener('click', (e) => {
                const wsId = el.dataset.wsId;
                const ws = CustomSim.workspaces.find(w => w.id === wsId);
                if (ws) ws.setOpOverride = null;
                CustomSim._renderWorkspaces();
                CustomSim.refreshPreview();
            });
        });

        // setOpOverride가 활성인 워크스페이스의 결과 복원
        CustomSim.workspaces.forEach(ws => {
            if (ws.setOpOverride) CustomSim._renderSetOpResult(ws.id);
        });

        // 결합 바 렌더
        CustomSim._renderCombineBar();
    },

    /**
     * 워크스페이스 추가
     */
    _addWorkspace: () => {
        const newId = `ws-${Date.now()}`;
        const newLabel = `W${CustomSim.workspaces.length + 1}`;
        CustomSim.workspaces.push({
            id: newId,
            label: newLabel,
            cards: [],
            transforms: [],
            mode: 'auto',
        });
        // combineOps 추가 (마지막 ws와 새 ws 사이 — 기본 union)
        if (CustomSim.workspaces.length > 1) {
            const leftWs = CustomSim.workspaces[CustomSim.workspaces.length - 2];
            CustomSim.combineOps.push({
                leftWsId: leftWs.id,
                op: 'union',
                rightWsId: newId,
            });
        }
        CustomSim.activeWsId = newId;
        CustomSim._renderWorkspaces();
    },

    /**
     * 워크스페이스 제거
     */
    _removeWorkspace: (wsId) => {
        if (CustomSim.workspaces.length <= 1) {
            alert('마지막 워크스페이스는 삭제할 수 없습니다.');
            return;
        }
        const idx = CustomSim.workspaces.findIndex(w => w.id === wsId);
        if (idx < 0) return;
        CustomSim.workspaces.splice(idx, 1);
        // combineOps 정리: idx번째 ws 제거 시 idx-1번째 op도 제거
        if (idx > 0 && CustomSim.combineOps.length >= idx) {
            CustomSim.combineOps.splice(idx - 1, 1);
        } else if (idx === 0 && CustomSim.combineOps.length > 0) {
            CustomSim.combineOps.shift();
        }
        // activeWsId 재설정
        if (CustomSim.activeWsId === wsId) {
            CustomSim.activeWsId = CustomSim.workspaces[0]?.id || 'ws-1';
        }
        CustomSim._renderWorkspaces();
        CustomSim.refreshPreview();
    },

    /**
     * 워크스페이스 내 집합 연산 계산 및 표시
     * op: 'union' | 'intersection' | 'difference' | 'complement' | 'symdiff'
     */
    _computeSetOp: (wsId, op) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;

        // 번호 배열을 가진 카드만 추출 (1~45 범위 정수만 유효)
        const cardSets = ws.cards
            .filter(c => c.numbers && c.numbers.length > 0)
            .map(c => [...new Set(
                c.numbers.map(n => parseInt(n)).filter(n => n >= 1 && n <= 45)
            )]);

        if (cardSets.length < 2) return;

        let result = [];

        switch (op) {
            case 'union': {
                // 모든 카드에 등장하는 번호 (중복 제거)
                const seen = new Set();
                for (const nums of cardSets) for (const n of nums) seen.add(n);
                result = [...seen].sort((a, b) => a - b);
                break;
            }
            case 'intersection': {
                // 모든 카드에 공통으로 있는 번호
                result = cardSets[0].filter(n =>
                    cardSets.slice(1).every(s => s.includes(n))
                ).sort((a, b) => a - b);
                break;
            }
            case 'difference': {
                // 첫 번째 카드에만 있고 나머지 카드에는 없는 번호 (A∖B∖C...)
                const otherNums = new Set(cardSets.slice(1).flat());
                result = cardSets[0]
                    .filter(n => !otherNums.has(n))
                    .sort((a, b) => a - b);
                break;
            }
            case 'complement': {
                // 1~45 중 어느 카드에도 없는 번호
                const allNums = new Set(cardSets.flat());
                result = Array.from({ length: 45 }, (_, i) => i + 1)
                    .filter(n => !allNums.has(n));
                break;
            }
            case 'symdiff': {
                // 정확히 하나의 카드에만 등장하는 번호
                const countMap = new Map();
                for (const nums of cardSets) {
                    for (const n of nums) {
                        countMap.set(n, (countMap.get(n) || 0) + 1);
                    }
                }
                result = [...countMap.entries()]
                    .filter(([, cnt]) => cnt === 1)
                    .map(([n]) => n)
                    .sort((a, b) => a - b);
                break;
            }
        }

        // override에 저장 → evaluateAt에서 이 번호가 산출로 사용됨
        ws.setOpOverride = { op, numbers: result };

        // 버튼 활성 상태 + clear 버튼 표시를 위해 재렌더
        CustomSim._renderWorkspaces();

        // 결과 div 채우기 (재렌더 후 DOM이 새로 만들어지므로 여기서 채움)
        CustomSim._renderSetOpResult(wsId);

        // 메인 산출 업데이트
        CustomSim.refreshPreview();
    },

    /**
     * 집합 연산 결과를 ws-setop-result div에 렌더
     */
    _renderSetOpResult: (wsId) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws?.setOpOverride) return;

        const resultEl = document.querySelector(`.ws-setop-result[data-ws-id="${wsId}"]`);
        if (!resultEl) return;

        const { op, numbers: result } = ws.setOpOverride;
        const opLabel = {
            union:        '∪ 합집합',
            intersection: '∩ 교집합',
            difference:   'A∖B 차집합',
            complement:   '∁ 미포함',
            symdiff:      '△ 대칭차',
        }[op] || op;

        const ballsHtml = result.length > 0
            ? result.map(n =>
                `<span class="ball ball-sm ${CustomSim._ballColor(n)}">${String(n).padStart(2, '0')}</span>`
              ).join('')
            : '<span class="text-xs text-slate-400 italic">없음</span>';

        resultEl.innerHTML = `
            <div class="flex items-center gap-2 flex-wrap py-1">
                <span class="text-[10px] font-semibold text-indigo-600">${opLabel}</span>
                <span class="text-[10px] font-bold text-indigo-400">→ 산출 적용 중</span>
                <span class="text-[10px] text-slate-400">${result.length}개</span>
                <span class="text-slate-200 text-[10px]">|</span>
                <div class="flex flex-wrap gap-1">${ballsHtml}</div>
            </div>
        `;
        resultEl.classList.remove('hidden');
    },

    /**
     * 결합 연산 바 렌더 (ws가 2개 이상일 때)
     */
    _renderCombineBar: () => {
        const bar = document.getElementById('ws-combine-bar');
        const opsEl = document.getElementById('ws-combine-ops');
        if (!bar || !opsEl) return;
        if (CustomSim.workspaces.length < 2) {
            bar.classList.add('hidden');
            return;
        }
        bar.classList.remove('hidden');
        // 예: W1 [op12] W2 [op23] W3
        let html = '';
        CustomSim.workspaces.forEach((ws, i) => {
            html += `<span class="text-xs font-bold text-slate-700">${ws.label}</span>`;
            if (i < CustomSim.workspaces.length - 1) {
                const op = CustomSim.combineOps[i]?.op || 'union';
                const opLabel = op === 'union' ? '∪' : op;
                html += `
                    <select class="select-underline text-xs ws-combine-op-sel" data-op-idx="${i}">
                        <option value="+" ${op === '+' ? 'selected' : ''}>+</option>
                        <option value="-" ${op === '-' ? 'selected' : ''}>−</option>
                        <option value="*" ${op === '*' ? 'selected' : ''}>×</option>
                        <option value="/" ${op === '/' ? 'selected' : ''}>÷</option>
                        <option value="%" ${op === '%' ? 'selected' : ''}>%</option>
                        <option value="union" ${op === 'union' ? 'selected' : ''}>∪ 합집합</option>
                        <option value="intersection" ${op === 'intersection' ? 'selected' : ''}>∩ 교집합 (공통)</option>
                        <option value="complement" ${op === 'complement' ? 'selected' : ''}>∁ 미포함 (1~45 중 외)</option>
                        <option value="difference" ${op === 'difference' ? 'selected' : ''}>\\ 차집합 (W1−W2)</option>
                        <option value="symdiff" ${op === 'symdiff' ? 'selected' : ''}>△ 대칭차 (한쪽에만)</option>
                    </select>
                `;
            }
        });
        opsEl.innerHTML = html;
        // 이벤트 바인딩
        opsEl.querySelectorAll('.ws-combine-op-sel').forEach(sel => {
            sel.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.opIdx);
                if (CustomSim.combineOps[idx]) {
                    CustomSim.combineOps[idx].op = e.target.value;
                    CustomSim.refreshPreview();
                }
            });
        });

        // ── 결합 후 변환 UI 렌더 ─────────────────────────────────────
        const postEl = document.getElementById('ws-combine-post');
        if (!postEl) return;
        postEl.classList.remove('hidden');

        const hasPost = CustomSim.combinePostTransforms.length > 0 || CustomSim.combinePostExpand;

        // 체인 표시
        const chainEl = document.getElementById('ws-post-chain');
        if (chainEl) {
            if (CustomSim.combinePostTransforms.length === 0) {
                chainEl.innerHTML = '<span class="text-[10px] text-slate-300 italic">변환 없음</span>';
            } else {
                chainEl.innerHTML = CustomSim.combinePostTransforms.map((t, i) => {
                    // [fix-372] post-combine 칩도 inline 편집
                    const sym = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': 'mod' }[t.op] || t.op;
                    const isTail = (t.op === '%' && t.value === 10);
                    if (isTail) {
                        return `<span class="ws-tx-chip text-[10px]">끝수<span class="ws-post-tx-x cursor-pointer ml-1" data-idx="${i}">✕</span></span>`;
                    }
                    return `<span class="ws-tx-chip text-[10px] inline-flex items-center gap-0.5" style="padding:2px 6px">
                        <span class="font-bold">${sym}</span>
                        <input type="number" class="ws-post-tx-val-edit" data-idx="${i}" value="${t.value}" style="width:42px;background:transparent;border:none;outline:none;text-align:center;font-size:10px;font-weight:700;color:inherit;padding:0;-moz-appearance:textfield" min="0">
                        <span class="ws-post-tx-x cursor-pointer" data-idx="${i}" style="margin-left:2px">✕</span>
                    </span>`;
                }).join('');
                chainEl.querySelectorAll('.ws-post-tx-x').forEach(el => {
                    el.addEventListener('click', (e) => {
                        const idx = parseInt(e.target.dataset.idx);
                        CustomSim.combinePostTransforms.splice(idx, 1);
                        CustomSim._renderCombineBar();
                        CustomSim.refreshPreview();
                    });
                });
            }
        }

        // 끝수 expand 버튼 상태 갱신
        const tailBtn = document.getElementById('ws-post-tail-btn');
        if (tailBtn) {
            tailBtn.classList.toggle('ws-tx-btn-active', CustomSim.combinePostExpand);
            tailBtn.textContent = CustomSim.combinePostExpand ? '끝수 expand ✓' : '끝수 expand';
        }

        // 초기화 버튼
        const resetBtn = document.getElementById('ws-post-reset-btn');
        if (resetBtn) {
            resetBtn.classList.toggle('hidden', !hasPost);
        }
    },

    /**
     * 결합 후 변환 이벤트 바인딩 (init에서 1회 호출)
     */
    _bindCombinePost: () => {
        // 끝수 expand 토글
        document.getElementById('ws-post-tail-btn')?.addEventListener('click', () => {
            CustomSim.combinePostExpand = !CustomSim.combinePostExpand;
            CustomSim._renderCombineBar();
            CustomSim.refreshPreview();
        });

        // 퀵 변환 버튼들
        document.querySelectorAll('.ws-post-tx-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const op = btn.dataset.op;
                const value = parseInt(btn.dataset.value);
                if (!op) return;
                CustomSim.combinePostTransforms.push({ op, value });
                CustomSim._renderCombineBar();
                CustomSim.refreshPreview();
            });
        });

        // 커스텀 변환 추가
        document.getElementById('ws-post-tx-add')?.addEventListener('click', () => {
            const op = document.getElementById('ws-post-tx-op')?.value || '+';
            const valStr = document.getElementById('ws-post-tx-val')?.value || '';
            const value = parseInt(valStr);
            if (isNaN(value) || value < 0) {
                alert('0 이상의 정수를 입력하세요.');
                return;
            }
            CustomSim.combinePostTransforms.push({ op, value });
            if (document.getElementById('ws-post-tx-val')) document.getElementById('ws-post-tx-val').value = '';
            CustomSim._renderCombineBar();
            CustomSim.refreshPreview();
        });
        // [fix-371] Enter 키로 결합 후 변환 추가
        document.getElementById('ws-post-tx-val')?.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            document.getElementById('ws-post-tx-add')?.click();
        });

        // 결합 후 전체 초기화
        document.getElementById('ws-post-reset-btn')?.addEventListener('click', () => {
            CustomSim.combinePostTransforms = [];
            CustomSim.combinePostExpand = false;
            CustomSim._renderCombineBar();
            CustomSim.refreshPreview();
        });
    },

    _renderWorkspaceCard: (c, idx, wsId) => {
        // Stage 6-5-1: op 토큰 렌더링 추가
        if (c.type === 'op') {
            const opSymbols = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': '%' };
            const opLabels = {
                '+': '각 원소별 덧셈 (broadcast)',
                '-': '각 원소별 뺄셈',
                '*': '각 원소별 곱셈',
                '/': '나머지 연산 (modulo)',
                '%': '나머지 연산'
            };
            const sym = opSymbols[c.value] || c.value;
            const label = opLabels[c.value] || '연산자';
            return `
                <div class="ws-op-badge" data-ws-x="${idx}" data-ws-id="${wsId}" title="${label} · 클릭하여 변경/제거">
                    ${sym}
                    <span class="ws-op-badge-x" data-ws-x="${idx}" data-ws-id="${wsId}">✕</span>
                </div>
            `;
        }
        // [fix-290] 저장된 필터 카드 렌더링
        if (c.type === 'saved') {
            const ws2 = CustomSim.workspaces.find(w => w.id === wsId);
            const isTailWs2 = ws2?.mode === 'tail';
            const tailFmt2 = (v) => `${((v % 10) + 10) % 10}끝`;
            const nums = c.targetNumbers || [];
            const display = nums.length > 8
                ? nums.slice(0, 8).map(n => isTailWs2 ? tailFmt2(n) : String(n).padStart(2,'0')).join(' ') + ` …+${nums.length - 8}`
                : nums.map(n => isTailWs2 ? tailFmt2(n) : String(n).padStart(2,'0')).join(' ');
            const typeLabel = c.savedType === 'custom' ? '커스텀' : '수동';
            const typeColor = c.savedType === 'custom' ? '#7c3aed' : '#0891b2';
            const typeBg = c.savedType === 'custom' ? '#f5f3ff' : '#cffafe';
            return `
                <div class="ws-card" style="border-color:${typeColor};background:${typeBg}80;" title="${typeLabel}: ${c.savedTitle} · ${nums.length}개 번호">
                    <div class="ws-card-head">
                        <span style="color:${typeColor}">📁 ${c.savedTitle.length > 12 ? c.savedTitle.substring(0,12) + '…' : c.savedTitle}</span>
                        <span class="ws-card-x" data-ws-x="${idx}" data-ws-id="${wsId}">✕</span>
                    </div>
                    <div class="ws-card-body" style="font-size:11px;letter-spacing:-0.02em">${display}</div>
                    <div class="ws-card-meta">${typeLabel} · ${nums.length}개</div>
                </div>
            `;
        }
        // [fix-267] regref 카드 렌더링 — 회귀@WS → 라인/보너스/포지션/회차 추출
        if (c.type === 'regref') {
            const sourceWs = CustomSim.workspaces.find(w => w.id === c.sourceWsId);
            const sourceLabel = sourceWs ? sourceWs.label : '?';
            const refLabelMap = {
                line: '전라인',
                bonus: '보너스',
                all_main_bonus: '전라인+보너스',
                pos: `${c.position}라인`,
                round: ({ ones: '회차일', tens: '회차십', hundreds: '회차백', thousands: '회차값' }[c.digitMode] || '회차값'),
            };
            const refLabel = refLabelMap[c.refType] || c.refType;
            return `
                <div class="ws-card" style="border-color:#0d9488;background:#ccfbf140;" title="회귀@${sourceLabel} → ${refLabel}: ${sourceLabel}의 산출값 N을 회귀 offset으로 사용 → sorted[targetIdx+N] 회차의 ${refLabel} 추출">
                    <div class="ws-card-head">
                        <span style="color:#0d9488">회귀@${sourceLabel}</span>
                        <span class="ws-card-x" data-ws-x="${idx}" data-ws-id="${wsId}">✕</span>
                    </div>
                    <div class="ws-card-body" style="font-size:12px;">→ ${refLabel}</div>
                    <div class="ws-card-meta">동적 회귀</div>
                </div>
            `;
        }

        const isKorea = CustomSim.currentDB === 'korea';
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        const isTailWs = ws?.mode === 'tail';
        // 끝수 표기 헬퍼 — value % 10 → "N끝" (음수 안전 처리)
        const tailFmt = (v) => `${((v % 10) + 10) % 10}끝`;
        // [fix-311] 해외 모드도 c.drawNo가 한국 회차로 매핑됨 (fix-310 옵션 B)
        const roundLabel = c.type === 'tail'
            ? '회차 무관'
            : (isKorea
                ? `${c.drawNo}회`
                : (c.drawNo ? `${c.drawNo}회 ⓚ` : `#${idx + 1}`));
        const offsetTxt = (c.type === 'tail')
            ? ''
            : ((c.offset != null && c.offset > 0) ? `현재−${c.offset}` : '');
        const colorMap = {
            line:    { color: '#4f46e5', bg: '#eef2ff', name: '전라인' },
            pos:     { color: '#7c3aed', bg: '#ede9fe', name: '라인' },
            num:     { color: '#059669', bg: '#d1fae5', name: '번호' },
            bonus:   { color: '#f59e0b', bg: '#fef3c7', name: '보너스' },
            round:   { color: '#d97706', bg: '#fef3c7', name: '회차' },
            date:    { color: '#db2777', bg: '#fce7f3', name: '일자' },
            tail:    { color: '#0d9488', bg: '#ccfbf1', name: '끝수' },
            combine: { color: '#0ea5e9', bg: '#e0f2fe', name: 'Σ결합' },
        };
        const cm = colorMap[c.type] || colorMap.line;
        const datePartLabel = { year: '년', month: '월', day: '일' };
        const cmName =
            (c.type === 'pos' && c.position) ? `${c.position}라인` :
            (c.type === 'date') ? `일자(${datePartLabel[c.datePart || 'day']})` :
            (c.type === 'tail') ? `끝수 ${c.tailNum}` :
            cm.name;

        let body = '';
        if (c.type === 'line') {
            body = c.numbers.map(n => isTailWs ? tailFmt(n) : String(n).padStart(2, '0')).join(' ');
        } else if (c.type === 'pos') {
            const sorted = [...(c.numbers || [])].sort((a, b) => a - b);
            const v = sorted[(c.position || 1) - 1];
            body = v != null ? (isTailWs ? tailFmt(v) : String(v).padStart(2, '0')) : '?';
        } else if (c.type === 'bonus') {
            body = c.bonus != null ? (isTailWs ? `+${tailFmt(c.bonus)}` : `+${String(c.bonus).padStart(2, '0')}`) : '?';
        } else if (c.type === 'num') {
            body = isTailWs ? tailFmt(c.num) : String(c.num).padStart(2, '0');
        } else if (c.type === 'round') {
            // digitMode: ones(%10) / tens(%100) / hundreds(%1000) / thousands(전체)
            const dm = c.digitMode || 'thousands';
            const mod = dm === 'ones' ? 10 : dm === 'tens' ? 100 : dm === 'hundreds' ? 1000 : null;
            const v = (c.drawNo != null && mod != null) ? (c.drawNo % mod) : c.drawNo;
            body = isTailWs ? tailFmt(v) : `${v}`;
        } else if (c.type === 'date') {
            if (c.drawDate) {
                const dt = new Date(c.drawDate);
                const part = c.datePart || 'day';
                const v = part === 'year' ? dt.getFullYear() :
                          part === 'month' ? dt.getMonth() + 1 :
                          dt.getDate();
                body = isTailWs ? tailFmt(v) : `${v}`;
            } else {
                body = '?';
            }
        } else if (c.type === 'tail') {
            // 끝수 카드 — 그 끝수에 속하는 번호 풀 표시
            const maxBall = (CustomSim.draws[0]?.maxBall) || 45;
            const nums = [];
            for (let n = 1; n <= maxBall; n++) {
                if (n % 10 === c.tailNum) nums.push(n);
            }
            body = nums.map(n => String(n).padStart(2, '0')).join(' ');
        } else if (c.type === 'combine') {
            // 결합 카드는 별도 처리 (자식 두 카드 표시)
            body = c.combineLabel || '?';
        }

        return `
            <div class="ws-card" style="border-color:${cm.color};background:${cm.bg}40;">
                <div class="ws-card-head">
                    <span style="color:${cm.color}">${cmName}</span>
                    <span class="ws-card-x" data-ws-x="${idx}" data-ws-id="${wsId}">✕</span>
                </div>
                <div class="ws-card-body">${body}</div>
                <div class="ws-card-meta">${roundLabel}${offsetTxt ? ' · ' + offsetTxt : ''}</div>
            </div>
        `;
    },

    // ============================================================
    // [legacy 호환] 기존 chip 빌더 진입점 — v5에서는 미사용
    // ============================================================
    _bindBuilder_LEGACY: () => {
        const cat = document.getElementById('tk-category');
        const round = document.getElementById('tk-round');
        const attr = document.getElementById('tk-attr');
        const tail = document.getElementById('tk-tail');
        const addBtn = document.getElementById('tk-add');
        const constInput = document.getElementById('tk-const');
        const addConstBtn = document.getElementById('tk-add-const');
        const resetBtn = document.getElementById('builder-reset');
        const undoBtn = document.getElementById('builder-undo');

        if (!cat || !addBtn) return;

        // 카테고리 변경 → 회차/속성 dropdown 동적 갱신
        cat.addEventListener('change', () => CustomSim._updateBuilderDropdowns());
        CustomSim._updateBuilderDropdowns();  // 초기화

        // 토큰 추가
        addBtn.addEventListener('click', () => CustomSim._addToken());

        // 연산자 추가
        document.querySelectorAll('.op-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                CustomSim._addOperator(btn.dataset.op);
            });
        });

        // 상수 추가
        if (addConstBtn) {
            addConstBtn.addEventListener('click', () => CustomSim._addConst());
            constInput?.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); CustomSim._addConst(); }
            });
        }

        // 전체 초기화 / 마지막 삭제
        resetBtn?.addEventListener('click', () => {
            CustomSim.formulaSteps = [];
            CustomSim._renderBuilder();
        });
        undoBtn?.addEventListener('click', () => {
            CustomSim.formulaSteps.pop();
            CustomSim._renderBuilder();
        });
    },

    /**
     * 카테고리에 따라 회차/속성 드롭다운 옵션 변경
     */
    _updateBuilderDropdowns: () => {
        const cat = document.getElementById('tk-category')?.value;
        const roundSel = document.getElementById('tk-round');
        const attrSel = document.getElementById('tk-attr');
        const tailLabel = document.getElementById('tk-tail')?.parentElement;
        if (!cat || !roundSel || !attrSel) return;

        // 회차 한글 라벨 — 전부 'N회차전' 형식으로 통일
        const roundLabels = {
            1: '1회차전', 2: '2회차전', 3: '3회차전',
            4: '4회차전', 5: '5회차전', 6: '6회차전',
            7: '7회차전', 8: '8회차전', 9: '9회차전', 10: '10회차전',
        };

        // 회차 옵션
        if (cat === 'draw') {
            roundSel.innerHTML = '<option value="0">현재 회차</option>';
            roundSel.disabled = true;
        } else {
            roundSel.disabled = false;
            roundSel.innerHTML = Array.from({length: 10}, (_, i) =>
                `<option value="${i+1}">${roundLabels[i+1]}</option>`).join('');
        }

        // 속성 옵션 (카테고리별)
        if (cat === 'main') {
            // 본번호 1~6구
            attrSel.innerHTML = Array.from({length: 6}, (_, i) =>
                `<option value="${i+1}">${i+1}구</option>`).join('');
            attrSel.disabled = false;
            if (tailLabel) tailLabel.style.display = '';
        } else if (cat === 'all_main' || cat === 'all_main_bonus') {
            // 집합 토큰 — 속성 선택 불필요
            attrSel.innerHTML = `<option value="all">전체</option>`;
            attrSel.disabled = true;
            if (tailLabel) tailLabel.style.display = '';
        } else if (cat === 'bonus') {
            attrSel.innerHTML = '<option value="b">보너스볼</option>';
            attrSel.disabled = true;
            if (tailLabel) tailLabel.style.display = '';
        } else if (cat === 'draw') {
            attrSel.innerHTML = `
                <option value="raw">그대로</option>
                <option value="digitSum">자릿합</option>
                <option value="tail">끝수(일의자리)</option>
            `;
            attrSel.disabled = false;
            if (tailLabel) tailLabel.style.display = 'none';
        } else if (cat === 'date') {
            attrSel.innerHTML = `
                <option value="year">년</option>
                <option value="month">월</option>
                <option value="day">일</option>
                <option value="weekday">요일(0=일~6=토)</option>
            `;
            attrSel.disabled = false;
            if (tailLabel) tailLabel.style.display = '';
        }
    },

    _addToken: () => {
        const cat = document.getElementById('tk-category')?.value;
        const round = parseInt(document.getElementById('tk-round')?.value || '1');
        const attrV = document.getElementById('tk-attr')?.value;
        const tail = document.getElementById('tk-tail')?.checked || false;

        // op 미존재 + 직전이 이미 토큰이면 자동 + 삽입
        if (CustomSim.formulaSteps.length > 0) {
            const last = CustomSim.formulaSteps[CustomSim.formulaSteps.length - 1];
            if (last.type !== 'op') {
                CustomSim.formulaSteps.push({ type: 'op', value: '+' });
            }
        }

        let tok;
        if (cat === 'main') {
            tok = { type: 'main', round, position: parseInt(attrV), tail };
        } else if (cat === 'all_main') {
            tok = { type: 'all_main', round, tail };
        } else if (cat === 'all_main_bonus') {
            tok = { type: 'all_main_bonus', round, tail };
        } else if (cat === 'bonus') {
            tok = { type: 'bonus', round, tail };
        } else if (cat === 'draw') {
            tok = { type: 'draw', attr: attrV };
        } else if (cat === 'date') {
            tok = { type: 'date', round, attr: attrV, tail };
        }
        if (tok) {
            CustomSim.formulaSteps.push(tok);
            CustomSim._renderBuilder();
        }
    },

    _addOperator: (op) => {
        // 빈 상태나 직전이 op면 직전 op만 교체
        if (CustomSim.formulaSteps.length === 0) return;
        const last = CustomSim.formulaSteps[CustomSim.formulaSteps.length - 1];
        if (last.type === 'op') {
            last.value = op;
        } else {
            CustomSim.formulaSteps.push({ type: 'op', value: op });
        }
        CustomSim._renderBuilder();
    },

    _addConst: () => {
        const inp = document.getElementById('tk-const');
        const v = parseInt(inp?.value || '');
        if (isNaN(v) || v < 0) {
            alert('상수는 0 이상의 정수를 입력하세요.');
            return;
        }
        if (CustomSim.formulaSteps.length > 0) {
            const last = CustomSim.formulaSteps[CustomSim.formulaSteps.length - 1];
            if (last.type !== 'op') {
                CustomSim.formulaSteps.push({ type: 'op', value: '+' });
            }
        }
        CustomSim.formulaSteps.push({ type: 'const', value: v });
        if (inp) inp.value = '';
        CustomSim._renderBuilder();
    },

    /**
     * chip 시퀀스 + 텍스트 변환 렌더
     */
    _renderBuilder: () => {
        const chipsEl = document.getElementById('builder-chips');
        const textEl = document.getElementById('builder-text');
        if (!chipsEl || !textEl) return;

        if (CustomSim.formulaSteps.length === 0) {
            chipsEl.innerHTML = '<span class="text-xs text-slate-400 italic">토큰을 추가하여 수식을 조립하세요. (chip 클릭 = 삭제)</span>';
            textEl.innerHTML = '<span class="text-slate-400">—</span>';
            return;
        }

        chipsEl.innerHTML = CustomSim.formulaSteps.map((tok, i) => {
            if (tok.type === 'op') {
                const sym = { '+': '+', '-': '−', '*': '×', '/': '÷', '%': 'mod' }[tok.value] || tok.value;
                return `<span class="chip-op-display" data-idx="${i}" title="클릭하여 삭제">${sym}</span>`;
            }
            const label = CustomSim._tokenLabel(tok);
            return `<span class="chip-removable" data-idx="${i}" title="클릭하여 삭제">${label}</span>`;
        }).join('');

        // chip 클릭 → 삭제
        chipsEl.querySelectorAll('[data-idx]').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.dataset.idx);
                CustomSim.formulaSteps.splice(idx, 1);
                // 양 끝의 op 제거 (정합성 유지)
                while (CustomSim.formulaSteps.length > 0 &&
                       CustomSim.formulaSteps[CustomSim.formulaSteps.length - 1].type === 'op') {
                    CustomSim.formulaSteps.pop();
                }
                while (CustomSim.formulaSteps.length > 0 &&
                       CustomSim.formulaSteps[0].type === 'op') {
                    CustomSim.formulaSteps.shift();
                }
                CustomSim._renderBuilder();
            });
        });

        // 텍스트 변환
        textEl.innerHTML = CustomSim.formulaSteps.map(tok => CustomSim._tokenText(tok)).join(' ');

        // 미리보기 갱신
        if (typeof CustomSim.refreshPreview === 'function') {
            CustomSim.refreshPreview();
        }
    },

    /**
     * chip 표시용 한글 label (예: '전회차 1구.끝')
     */
    _tokenLabel: (tok) => {
        const rLabels = {1:'1회차전', 2:'2회차전', 3:'3회차전', 4:'4회차전', 5:'5회차전', 6:'6회차전', 7:'7회차전', 8:'8회차전', 9:'9회차전', 10:'10회차전'};
        if (tok.type === 'main') {
            return `${rLabels[tok.round]||('N-'+tok.round)} ${tok.position}구${tok.tail ? '.끝' : ''}`;
        }
        if (tok.type === 'all_main') {
            return `${rLabels[tok.round]||('N-'+tok.round)} 전라인${tok.tail ? '.끝' : ''}`;
        }
        if (tok.type === 'all_main_bonus') {
            return `${rLabels[tok.round]||('N-'+tok.round)} 전라인+보너스${tok.tail ? '.끝' : ''}`;
        }
        if (tok.type === 'bonus') {
            return `${rLabels[tok.round]||('N-'+tok.round)} 보너스${tok.tail ? '.끝' : ''}`;
        }
        if (tok.type === 'draw') {
            const m = { raw: '회차', digitSum: '회차.자릿합', tail: '회차.끝' };
            return m[tok.attr] || '회차';
        }
        if (tok.type === 'date') {
            const m = { year: '년', month: '월', day: '일', weekday: '요일' };
            return `${rLabels[tok.round]||('N-'+tok.round)} ${m[tok.attr] || tok.attr}${tok.tail ? '.끝' : ''}`;
        }
        if (tok.type === 'const') return String(tok.value);
        return '?';
    },

    /**
     * 텍스트 변환용 영문 표기 (예: 'N-1[1].tail')
     */
    _tokenText: (tok) => {
        if (tok.type === 'op') return tok.value;
        if (tok.type === 'main') {
            return `N-${tok.round}[${tok.position}]${tok.tail ? '.tail' : ''}`;
        }
        if (tok.type === 'all_main') {
            return `N-${tok.round}[*]${tok.tail ? '.tail' : ''}`;
        }
        if (tok.type === 'all_main_bonus') {
            return `N-${tok.round}[*+b]${tok.tail ? '.tail' : ''}`;
        }
        if (tok.type === 'bonus') {
            return `N-${tok.round}[b]${tok.tail ? '.tail' : ''}`;
        }
        if (tok.type === 'draw') {
            return `drawNo${tok.attr === 'raw' ? '' : '.' + tok.attr}`;
        }
        if (tok.type === 'date') {
            return `N-${tok.round}.${tok.attr}${tok.tail ? '.tail' : ''}`;
        }
        if (tok.type === 'const') return String(tok.value);
        return '?';
    },

    // ============================================================
    // S6 — 평가 엔진 (수식 → 결과 + 보정 + 로그)
    // ============================================================

    /**
     * 토큰 평가 — 항상 { values: [...], isSet: bool } 형태로 반환
     *   isSet=true: 집합 토큰 (전라인 등)
     *   isSet=false: 단일 값
     */
    _evalToken: (tok, draws, targetIdx) => {
        const single = (v) => ({ values: [v], isSet: false });
        const setOf  = (vs) => ({ values: vs, isSet: true });

        if (tok.type === 'const') return single(tok.value);

        if (tok.type === 'main') {
            const d = draws[targetIdx + tok.round];
            if (!d) return single(0);
            const v = d.numbers[tok.position - 1] || 0;
            return single(tok.tail ? (v % 10) : v);
        }
        if (tok.type === 'all_main') {
            const d = draws[targetIdx + tok.round];
            if (!d) return setOf([]);
            const vs = (d.numbers || []).map(v => tok.tail ? (v % 10) : v);
            return setOf(vs);
        }
        if (tok.type === 'all_main_bonus') {
            const d = draws[targetIdx + tok.round];
            if (!d) return setOf([]);
            const list = [...(d.numbers || [])];
            if (d.bonus) list.push(d.bonus);
            if (d.bonus2) list.push(d.bonus2);
            return setOf(list.map(v => tok.tail ? (v % 10) : v));
        }
        if (tok.type === 'bonus') {
            const d = draws[targetIdx + tok.round];
            if (!d || !d.bonus) return single(0);
            return single(tok.tail ? (d.bonus % 10) : d.bonus);
        }
        if (tok.type === 'draw') {
            const d = draws[targetIdx];
            if (!d) return single(0);
            const no = d.drawNo || 0;
            if (tok.attr === 'raw') return single(no);
            if (tok.attr === 'digitSum') {
                return single(String(no).split('').reduce((s, c) => s + (parseInt(c) || 0), 0));
            }
            if (tok.attr === 'tail') return single(no % 10);
        }
        if (tok.type === 'date') {
            const d = draws[targetIdx + tok.round];
            if (!d || !d.drawDate) return single(0);
            const dt = new Date(d.drawDate);
            let v = 0;
            if (tok.attr === 'year') v = dt.getFullYear();
            else if (tok.attr === 'month') v = dt.getMonth() + 1;
            else if (tok.attr === 'day') v = dt.getDate();
            else if (tok.attr === 'weekday') v = dt.getDay();
            return single(tok.tail ? (v % 10) : v);
        }
        return single(0);
    },

    /**
     * 두 결과 결합:
     *   set op scalar → element-wise
     *   scalar op set → element-wise
     *   set op set    → 합집합 (concat)
     *   scalar op scalar → 단일
     */
    _applyOp: (a, op, b) => {
        const doOp = (x, y) => {
            switch (op) {
                case '+': return x + y;
                case '-': return x - y;
                case '*': return x * y;
                case '/': return y === 0 ? 0 : Math.floor(x / y);
                case '%': return y === 0 ? 0 : (x % y);
            }
            return x;
        };
        if (a.isSet && !b.isSet) {
            const s = b.values[0] || 0;
            return { values: a.values.map(v => doOp(v, s)), isSet: true };
        }
        if (!a.isSet && b.isSet) {
            const s = a.values[0] || 0;
            return { values: b.values.map(v => doOp(s, v)), isSet: true };
        }
        if (a.isSet && b.isSet) {
            return { values: [...a.values, ...b.values], isSet: true };
        }
        return { values: [doOp(a.values[0] || 0, b.values[0] || 0)], isSet: false };
    },

    /**
     * 좌→우 순차 연산
     */
    _evalSequential: (steps, draws, targetIdx) => {
        if (!steps || steps.length === 0) return { result: null, valid: false };
        if (steps[0].type === 'op') return { result: null, valid: false };

        let acc = CustomSim._evalToken(steps[0], draws, targetIdx);
        for (let i = 1; i < steps.length; i += 2) {
            const op = steps[i];
            const next = steps[i + 1];
            if (!op || op.type !== 'op' || !next) break;
            const v = CustomSim._evalToken(next, draws, targetIdx);
            acc = CustomSim._applyOp(acc, op.value, v);
        }
        return { result: acc, valid: true };
    },

    // ============================================================
    // S7 — 전체 회차 시뮬레이션 (계산값 + 당첨개수 현황 매트릭스)
    //   사용자 결정: 단일 회차 산출 X → 모든 회차에 수식 적용 후 적중 비교
    // ============================================================
    /**
     * 미리보기 + 매트릭스 갱신 — 150ms debounce 적용 (연속 호출 시 마지막만 실행)
     * 이전: 더블클릭 시마다 매번 122회 walk-forward 평가 → 느림
     * 이후: 사용자 입력 정착(150ms) 후에만 평가 → 반응 속도 향상
     */
    refreshPreview: () => {
        if (CustomSim._refreshPreviewTimer) clearTimeout(CustomSim._refreshPreviewTimer);
        CustomSim._refreshPreviewTimer = setTimeout(() => {
            CustomSim._refreshPreviewTimer = null;
            CustomSim._refreshPreviewImpl();
        }, 150);
    },

    /**
     * 실제 미리보기 갱신 로직 (debounce 후 호출)
     */
    _refreshPreviewImpl: () => {
        const el = document.getElementById('preview-area');
        const saveBtn = document.getElementById('btn-save');
        if (!el) return;

        // v5-multi — 모든 ws 비어 있으면 안내 표시
        const hasCards = CustomSim.workspaces.some(ws => ws.cards.length > 0);
        if (!hasCards) {
            el.innerHTML = `
                <div class="text-sm text-slate-400 italic py-12 text-center">
                    좌측 회차의 chip(전라인/회차/일자)을 작업공간에 끌어 놓으면 모든 회차에 일반화 적용 + 적중 검증을 자동 수행합니다.
                </div>`;
            if (saveBtn) saveBtn.disabled = true;
            return;
        }
        if (saveBtn) saveBtn.disabled = false;
        if (CustomSim.draws.length === 0) {
            el.innerHTML = '<div class="text-sm text-slate-400 italic py-8 text-center">회차 데이터 없음</div>';
            return;
        }

        // workspace 카드의 최대 offset = 일반화 시 필요한 lookback (모든 ws 통합)
        let maxLookback = 0;
        for (const ws of CustomSim.workspaces) {
            for (const c of ws.cards) {
                maxLookback = Math.max(maxLookback, c.offset || 0);
            }
        }

        // 전회차 분석 (limit 제거)
        const isKorea = CustomSim.currentDB === 'korea';
        const draws = CustomSim.draws;
        const limit = Math.max(0, draws.length - maxLookback);
        const rows = [];
        let totalHitNumbers = 0;
        let zeroHitRounds = 0;
        let maxHitInRound = 0;

        // ── simNow(미추첨 다음 회차) 예측 행 — 한국 로또일 때만 최상단 prepend ──
        if (isKorea && draws.length > 0) {
            const evSim = CustomSim.evaluateAt(-1);
            const latest = draws[0];
            const nextDate = latest?.drawDate ? new Date(latest.drawDate) : null;
            if (nextDate) nextDate.setDate(nextDate.getDate() + 7);
            rows.push({
                target: {
                    drawNo: (latest?.drawNo || 0) + 1,
                    drawDate: nextDate ? nextDate.toISOString() : null,
                    numbers: [],
                    bonus: null,
                    _pending: true,
                },
                predicted: evSim.normalizedSet || [],
                hits: [],
                bonusHits: [],
                hitCount: 0,
                isBonusHit: false,
                logs: evSim.logs,
                isPending: true,
            });
        }

        // [fix-259] 비교용 한국 당첨번호 매칭 헬퍼
        // 해외 로또 선택 시: 해외 데이터로 chip 산출 → 한국 동일 drawNo 당첨번호와 비교
        // 한국 로또 선택 시: target 자체 사용 (기존 동작 유지)
        const _isKorea = (CustomSim.currentDB === 'korea' || draws[0]?.dbId === 'korea');
        // [fix-324] _getKoreaTarget — 한국 매핑이 없거나 미추첨이면 null 반환 (잘못된 fallback 제거)
        //   이전: koreaDraws[0](=한국 latest) 반환 → 1223 미추첨인데 1222 번호로 적중 비교됨 (오류)
        const _getKoreaTarget = (target) => {
            if (_isKorea) return target;
            // 해외 → 한국 매칭: drawNo로 정확한 한국 row만 사용
            const koreaByNo = CustomSim.koreaDrawByNo || {};
            const krRow = koreaByNo[target.drawNo];
            if (krRow && Array.isArray(krRow.numbers) && krRow.numbers.length > 0) {
                return krRow; // 한국 추첨 완료된 매핑 회차만
            }
            return null; // 미추첨 또는 매핑 없음 → 적중 비교 X
        };

        for (let i = 0; i < limit; i++) {
            const target = draws[i];
            const ev = CustomSim.evaluateAt(i);
            const predicted = ev.normalizedSet || [];
            // [fix-259/324] 비교 대상: 한국 로또 당첨번호 (한국 미추첨이면 null → 적중 0)
            const compareDraw = _getKoreaTarget(target);
            const actualSet = compareDraw ? new Set(compareDraw.numbers || []) : new Set();
            const bonusVals = compareDraw ? [compareDraw.bonus, compareDraw.bonus2].filter(Boolean) : [];

            const hits = predicted.filter(n => actualSet.has(n));
            const bonusHits = predicted.filter(n => bonusVals.includes(n));
            const hitCount = hits.length;

            if (hitCount === 0) zeroHitRounds++;
            totalHitNumbers += hitCount;
            if (hitCount > maxHitInRound) maxHitInRound = hitCount;

            rows.push({
                target,
                predicted,
                hits,
                bonusHits,
                hitCount,
                isBonusHit: bonusHits.length > 0,
                logs: ev.logs,
                isSet: ev.isSet,
            });
        }

        // 통계 (simNow 예측 행은 제외)
        const realRows = rows.filter(r => !r.isPending);
        const total = realRows.length;
        const hitRounds = realRows.filter(r => r.hitCount > 0).length;
        const avgHitRate = total > 0 ? (hitRounds / total * 100).toFixed(1) : '0.0';
        const zeroHitRate = total > 0 ? (zeroHitRounds / total * 100).toFixed(1) : '0.0';
        const bonusHitCount = realRows.filter(r => r.isBonusHit).length;

        // 최근 N회차 평균 적중수 (realRows는 round DESC 정렬 → slice(0, n)이 최근 n회)
        const _avgRecent = (n) => {
            const slice = realRows.slice(0, n);
            if (slice.length === 0) return '0.0';
            const sum = slice.reduce((acc, r) => acc + (r.hitCount || 0), 0);
            return (sum / slice.length).toFixed(1);
        };
        const avgRecent10 = _avgRecent(10);
        const avgRecent5  = _avgRecent(5);
        const avgRecent3  = _avgRecent(3);

        // ── 미당첨 gap 계산 (시간 ASC 순 = 과거→현재) ──
        // 직전 적중 회차 이후 그 회차까지 몇 번째 미적중인지
        // 예: 1219 적중 → 1220=1회, 1221=2회, 1222=3회 미당첨
        // rows는 round DESC 정렬이므로 ASC로 뒤집어서 누적 계산 후 원래 위치에 부여
        const realRowsForGap = rows.filter(r => !r.isPending);
        const ascRows = [...realRowsForGap].reverse();  // 과거(작은 회차) → 현재
        let gap = 0;
        for (const r of ascRows) {
            if (r.hitCount > 0) {
                gap = 0;
                r.gapSinceHit = 0;
            } else {
                gap += 1;
                r.gapSinceHit = gap;
            }
        }
        // simNow(예정) 행은 별도 처리 (미추첨이라 gap 의미 없음 → null)
        for (const r of rows) {
            if (r.isPending) r.gapSinceHit = null;
        }

        // ── 매트릭스 행 렌더 ──
        const predSet = (preds, hits, bonHits) => {
            if (!preds || preds.length === 0) {
                return '<span class="text-xs text-slate-300">—</span>';
            }
            return preds.map(n => {
                const isHit = hits.includes(n);
                const isB = bonHits.includes(n);
                return `<span class="ball ball-sm ${CustomSim._ballColor(n)} ${isHit ? 'ball-hit' : ''} ${isB ? 'ball-bonus' : ''}">${String(n).padStart(2, '0')}</span>`;
            }).join('');
        };

        // 미적중 ball dim 스타일 (옅은 회색 배경 + 옅은 회색 글씨)
        const dimStyle = 'background:#f1f5f9 !important;color:#cbd5e1 !important;box-shadow:none !important;';

        const matrixRows = rows.map(r => {
            // [fix-311] 해외 모드도 r.target.drawNo가 한국 회차로 매핑됨 (fix-310 옵션 B)
            // → 해외에서도 한국 회차 라벨 표시 + ⓚ 마커
            const pendingMark = r.isPending ? ' <span class="text-[9px] font-medium text-amber-500">(예정)</span>' : '';
            const roundLabel = isKorea
                ? `${r.target.drawNo}회${pendingMark}`
                : (r.target.drawNo
                    ? `${r.target.drawNo}회 <span class="text-[9px] text-slate-400 font-medium">ⓚ</span>${pendingMark}`
                    : '-');

            // [fix-322/323] 매트릭스 당첨번호 컬럼 = 한국 매핑 회차의 한국 당첨번호
            //   - 해외 모드 (korRound 존재): korNumbers/korBonus만 사용 (미추첨이면 빈 배열 — 해외 번호 fallback X)
            //   - 한국 모드: target.numbers/bonus 사용 (target 자체가 한국 row)
            const predictedSet = new Set(r.predicted);
            const isOverseasMode = (r.target.korRound != null);
            const koreanWinNums = isOverseasMode
                ? (r.target.korNumbers || [])      // 해외 모드: 한국 매핑 데이터만 (미추첨이면 빈)
                : (r.target.numbers || []);         // 한국 모드: target 자체
            const koreanBonus = isOverseasMode
                ? r.target.korBonus                  // 해외 모드: 한국 보너스 (미추첨이면 null)
                : r.target.bonus;                    // 한국 모드: target 보너스
            const actualHtml = koreanWinNums.map(n => {
                const hit = predictedSet.has(n);
                return hit
                    ? `<span class="ball ball-sm ${CustomSim._ballColor(n)} ball-hit">${String(n).padStart(2, '0')}</span>`
                    : `<span class="ball ball-sm" style="${dimStyle}">${String(n).padStart(2, '0')}</span>`;
            }).join('');
            const bonHtml = koreanBonus
                ? (predictedSet.has(koreanBonus)
                    ? `<span class="ball ball-sm ${CustomSim._ballColor(koreanBonus)} ball-bonus ball-hit">${String(koreanBonus).padStart(2, '0')}</span>`
                    : `<span class="ball ball-sm ball-bonus" style="${dimStyle}">${String(koreanBonus).padStart(2, '0')}</span>`)
                : '';

            // 적중 셀 — 적중 시 ★N개 / 미적중 시 미당첨 gap 표시
            const hitBadge = r.isPending
                ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold text-amber-700 bg-amber-50">예측</span>`
                : r.hitCount > 0
                    ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold text-emerald-700 bg-emerald-50">★ ${r.hitCount}개</span>`
                    : r.isBonusHit
                        ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold text-amber-700 bg-amber-50">B 적중</span>`
                        : `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium text-slate-400 bg-slate-50" title="직전 적중 이후 ${r.gapSinceHit}회차 미적중">${r.gapSinceHit}회 미당첨</span>`;

            const logBadge = (r.logs && r.logs.length > 0)
                ? `<sup class="ml-0.5 text-slate-300 text-[9px]" title="보정: ${r.logs.join(', ')}">*</sup>`
                : '';

            const rowStyle = r.isPending
                ? 'background:linear-gradient(135deg,#fef3c7 0%,#fff 60%);border-left:3px solid #f59e0b;'
                : '';
            const roundColor = r.isPending ? 'text-amber-700' : 'text-slate-900';

            // 산출 번호 개수
            const predCount = (r.predicted || []).length;
            const countCell = predCount > 0
                ? `<span class="inline-flex items-center justify-center px-2 py-0.5 rounded text-[11px] font-bold text-slate-700 bg-slate-100">${predCount}</span>`
                : `<span class="text-[11px] text-slate-300">·</span>`;

            return `
                <tr class="border-b border-slate-100 hover:bg-slate-50/30 transition-colors" style="${rowStyle}">
                    <td class="py-1.5 px-2 text-sm font-bold ${roundColor} whitespace-nowrap">${roundLabel}</td>
                    <td class="py-1.5 px-2">
                        <div class="flex items-center gap-1 flex-wrap">
                            ${predSet(r.predicted, r.hits, r.bonusHits)}
                            ${logBadge}
                        </div>
                    </td>
                    <td class="py-1.5 px-2 text-center whitespace-nowrap">${countCell}</td>
                    <td class="py-1.5 px-2 whitespace-nowrap">
                        <div class="flex items-center gap-1">
                            ${r.isPending
                                ? '<span class="text-xs text-slate-300 italic">미추첨</span>'
                                : actualHtml + (bonHtml ? `<span class="text-xs text-slate-300 mx-0.5">+</span>${bonHtml}` : '')}
                        </div>
                    </td>
                    <td class="py-1.5 px-2 text-center whitespace-nowrap">${hitBadge}</td>
                </tr>
            `;
        }).join('');

        el.innerHTML = `
            <!-- KPI 7 카드 (메인 4 + 최근 N회차 평균 3) — 1행 통합 -->
            <div class="kpi-grid border-y border-slate-100 mb-5">
                <div class="kpi-cell">
                    <div class="kpi-value text-emerald-600">${avgHitRate}%</div>
                    <div class="kpi-label">적중 회차 비율</div>
                </div>
                <div class="kpi-cell">
                    <div class="kpi-value">${maxHitInRound}</div>
                    <div class="kpi-label">최고 적중수</div>
                </div>
                <div class="kpi-cell">
                    <div class="kpi-value text-amber-600">${bonusHitCount}</div>
                    <div class="kpi-label">보너스 적중 회차</div>
                </div>
                <div class="kpi-cell">
                    <div class="kpi-value text-slate-400">${zeroHitRate}%</div>
                    <div class="kpi-label">0-적중 회차</div>
                </div>
                <div class="kpi-cell sub">
                    <div class="kpi-value">${avgRecent10}</div>
                    <div class="kpi-label">최근 10회 평균</div>
                </div>
                <div class="kpi-cell sub">
                    <div class="kpi-value">${avgRecent5}</div>
                    <div class="kpi-label">최근 5회 평균</div>
                </div>
                <div class="kpi-cell sub">
                    <div class="kpi-value">${avgRecent3}</div>
                    <div class="kpi-label">최근 3회 평균</div>
                </div>
            </div>

            <!-- Hit 추이 sparkline -->
            <div class="mb-5">
                <div class="flex items-center justify-between mb-2">
                    <span class="h-section">최근 100회차 적중 추이</span>
                    <span class="meta">★ = 적중 회차</span>
                </div>
                <div class="border border-slate-100 rounded-lg p-3" style="height: 110px; position: relative;">
                    <canvas id="hit-trend-chart"></canvas>
                </div>
            </div>

            <!-- 매트릭스 -->
            <div class="text-xs text-slate-500 mb-2 flex items-center justify-between mt-4">
                <span>전체 ${total}회차 분석${isKorea ? ' + 다음 회차 예측' : ''}</span>
                <span class="meta">★ = 본번호 적중 / B = 보너스 적중</span>
            </div>
            <div class="border-t border-slate-100">
                <table class="w-full">
                    <thead>
                        <tr style="background:#334155;">
                            <th class="py-2.5 px-2 text-left text-[10px] font-bold text-white uppercase tracking-wider" style="width:70px;">회차</th>
                            <th class="py-2.5 px-2 text-left text-[10px] font-bold text-white uppercase tracking-wider" style="width:auto;">산출</th>
                            <th class="py-2.5 px-2 text-center text-[10px] font-bold text-white uppercase tracking-wider" style="width:50px;">개수</th>
                            <th class="py-2.5 px-2 text-left text-[10px] font-bold text-white uppercase tracking-wider" style="width:1%;white-space:nowrap;">당첨번호</th>
                            <th class="py-2.5 px-2 text-center text-[10px] font-bold text-white uppercase tracking-wider" style="width:90px;">적중</th>
                        </tr>
                    </thead>
                    <tbody>${matrixRows}</tbody>
                </table>
            </div>
        `;

        // ── Hit 추이 sparkline 그리기 ──
        CustomSim._renderHitTrendChart(rows.slice(0, 100));
    },

    /**
     * 최근 N회차 hit 추이 sparkline (Chart.js)
     */
    _renderHitTrendChart: (rows) => {
        const canvas = document.getElementById('hit-trend-chart');
        if (!canvas || typeof Chart === 'undefined') return;

        // 기존 차트 제거 (메모리 누수 방지)
        if (CustomSim._chart) {
            CustomSim._chart.destroy();
            CustomSim._chart = null;
        }

        // rows는 round DESC. 차트는 시간순(ASC)으로 표시
        const ascRows = [...rows].reverse();
        const labels = ascRows.map(r => r.target.drawNo || '');
        const data = ascRows.map(r => r.hitCount);
        const colors = ascRows.map(r => r.hitCount > 0 ? '#059669' : '#cbd5e1');

        CustomSim._chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: '적중 개수',
                    data,
                    backgroundColor: colors,
                    borderRadius: 2,
                    barThickness: 'flex',
                    maxBarThickness: 8,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 250 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        titleFont: { size: 11, weight: 700 },
                        bodyFont: { size: 11 },
                        padding: 8,
                        callbacks: {
                            title: (items) => `${items[0].label}회`,
                            label: (item) => `적중 ${item.parsed.y}개`,
                        }
                    }
                },
                scales: {
                    x: { display: false },
                    y: {
                        beginAtZero: true,
                        max: Math.max(2, Math.max(...data)),
                        ticks: { font: { size: 10 }, color: '#94a3b8', stepSize: 1 },
                        grid: { color: '#f1f5f9', drawBorder: false }
                    }
                }
            }
        });
    },

    /**
     * [DEPRECATED 2026-05-03] simulator_evaluator.js로 이전됨.
     * 단일 값 보정 (0 → null / 음수 → 역산 / 초과 → 순환)
     */
    _normalizeOne: (v, maxBall) => {
        if (v === 0) return { value: null, note: '0' };
        if (v < 0) {
            const r = maxBall + (v % maxBall);
            if (r === 0) return { value: null, note: `${v}→0` };
            return { value: r, note: `${v}→${r}` };
        }
        if (v > maxBall) {
            const r = ((v - 1) % maxBall) + 1;
            return { value: r, note: `${v}→${r}` };
        }
        return { value: v, note: null };
    },

    /**
     * v5 — 작업공간 카드를 일반화하여 targetIdx 회차에 적용 → 산출 set
     * @returns {rawValues, normalizedSet, logs, valid}
     */
    /**
     * v5-multi: 다중 워크스페이스 평가 (결합 연산 적용)
     * ★ 2026-05-03: simulator_evaluator.js로 위임 (단일 source of truth)
     */
    evaluateAt: (targetIdx) => {
        if (!CustomSim.draws?.length || CustomSim.workspaces.length === 0) {
            return { rawValues: [], normalizedSet: [], logs: [], valid: false };
        }
        // simulator_evaluator.js가 로드되지 않은 경우 fallback (정상 동작 시 발생하지 않음)
        if (typeof window.evalSimulatorFormulaForDraw !== 'function') {
            console.error('[customSimulator] simulator_evaluator.js not loaded — cannot evaluate');
            return { rawValues: [], normalizedSet: [], logs: [], valid: false };
        }

        const draws = CustomSim.draws;
        let targetRound;
        if (targetIdx === -1 && CustomSim.currentDB === 'korea') {
            // simNow (미추첨 다음 회차)
            const latest = draws[0];
            targetRound = ((latest?.drawNo || latest?.round) || 0) + 1;
        } else {
            const target = draws[targetIdx];
            if (!target) return { rawValues: [], normalizedSet: [], logs: [], valid: false };
            targetRound = target.drawNo || target.round;
        }
        if (!targetRound) return { rawValues: [], normalizedSet: [], logs: [], valid: false };

        // formulaSteps 빌드 (v5-multi 객체 형식)
        const formulaSteps = {
            workspaces: CustomSim.workspaces,
            combineOps: CustomSim.combineOps,
            combinePostTransforms: CustomSim.combinePostTransforms,
            combinePostExpand: CustomSim.combinePostExpand,
            pattern: CustomSim.pattern || 'none',
            version: 'v5-multi',
        };
        const maxBall = draws[0]?.maxBall || 45;

        // simulator_evaluator.js의 evalSimulatorFormulaForDraw 호출 (withLogs 모드)
        const evalResult = window.evalSimulatorFormulaForDraw(
            formulaSteps,
            draws,
            targetRound,
            maxBall,
            { withLogs: true }
        );

        // evalResult: { result: number[], logs: string[] } 또는 number[] (fallback)
        if (Array.isArray(evalResult)) {
            // withLogs 옵션 미적용 (레거시 버전) → logs 없음
            return { rawValues: evalResult, normalizedSet: evalResult, logs: [], valid: true };
        } else {
            // withLogs 적용 → result + logs
            return {
                rawValues: evalResult.result || [],
                normalizedSet: evalResult.result || [],
                logs: evalResult.logs || [],
                valid: true,
            };
        }
    },

    /**
     * [DEPRECATED 2026-05-03] simulator_evaluator.js로 이전됨.
     * 단일 워크스페이스 평가 (카드 → 값 산출 → 변환 적용)
     * evaluateAt이 simulator_evaluator.js로 위임하므로 더 이상 사용하지 않음.
     */
    _evaluateWorkspace: (ws, draws, targetIdx, target) => {
        const allValues = [];
        for (const c of ws.cards) {
            // 끝수 카드는 회차 무관 → refDraw 불필요
            if (c.type === 'tail') {
                const maxBall = target?.maxBall || 45;
                for (let n = 1; n <= maxBall; n++) {
                    if (n % 10 === c.tailNum) allValues.push(n);
                }
                continue;
            }

            let refDraw;
            if (CustomSim.currentDB === 'korea') {
                refDraw = draws[targetIdx + c.offset];
            } else {
                refDraw = draws.find(d => d.drawNo === c.drawNo);
            }
            // round/date 카드는 refDraw 없어도 target fallback으로 산출
            // 다른 type(line/pos/bonus/num)은 refDraw 필수
            if (!refDraw && c.type !== 'round' && c.type !== 'date') continue;

            if (c.type === 'line') {
                allValues.push(...(refDraw.numbers || []));
            } else if (c.type === 'pos') {
                const sorted = [...(refDraw.numbers || [])].sort((a, b) => a - b);
                const v = sorted[(c.position || 1) - 1];
                if (v != null) allValues.push(v);
            } else if (c.type === 'bonus') {
                if (refDraw.bonus != null) allValues.push(refDraw.bonus);
            } else if (c.type === 'num') {
                if (CustomSim.currentDB === 'korea') {
                    const ballPos = c.num != null ? (refDraw.numbers || [])[(target.numbers?.indexOf(c.num) ?? 0)] : null;
                    if (ballPos != null) allValues.push(ballPos);
                    else allValues.push(c.num);
                } else {
                    allValues.push(c.num);
                }
            } else if (c.type === 'round') {
                // refDraw 우선 → target fallback → c.drawNo (원본 드래그 시점)
                let v = refDraw?.drawNo ?? target?.drawNo ?? c.drawNo;
                // digitMode 적용 (ones/tens/hundreds/thousands)
                const dm = c.digitMode || 'thousands';
                const mod = dm === 'ones' ? 10 : dm === 'tens' ? 100 : dm === 'hundreds' ? 1000 : null;
                if (v != null && mod != null) v = v % mod;
                if (v != null) allValues.push(v);
            } else if (c.type === 'date') {
                const dateStr = refDraw?.drawDate ?? target?.drawDate ?? c.drawDate;
                if (dateStr) {
                    const dt = new Date(dateStr);
                    const part = c.datePart || 'day';
                    let v = null;
                    if (part === 'year') v = dt.getFullYear();          // 2025
                    else if (part === 'month') v = dt.getMonth() + 1;   // 1~12
                    else v = dt.getDate();                              // 1~31 (day)
                    if (v != null) allValues.push(v);
                }
            }
        }

        // 변환 적용 — 분기(branching) 모드
        // 각 변환을 원본값에 독립 적용 → 모든 분기 결과의 합집합
        // 예: +1, -1 두 변환 → [원본+1] ∪ [원본-1] (누적이 아니라 두 set 합집합)
        // 사용자가 "원본 그대로"도 포함하려면 +0 변환을 추가
        let working;
        if (ws.transforms.length === 0) {
            working = [...allValues];
        } else {
            const applyTx = (v, tx) => {
                switch (tx.op) {
                    case '+': return v + tx.value;
                    case '-': return v - tx.value;
                    case '*': return v * tx.value;
                    case '/': return tx.value === 0 ? 0 : Math.floor(v / tx.value);
                    case '%': return tx.value === 0 ? 0 : (v % tx.value);
                }
                return v;
            };
            const branches = ws.transforms.map(tx => allValues.map(v => applyTx(v, tx)));
            working = branches.flat();
        }

        // mode 처리
        if (ws.mode === 'scalar' && working.length > 1) {
            working = [working.reduce((s, v) => s + v, 0)];
        } else if (ws.mode === 'tail') {
            // 끝수 expand 모드: working의 모든 값 → % 10 (끝수) → 그 끝수의 1~maxBall 모든 번호
            const maxBall = target?.maxBall || 45;
            const tailSet = new Set(working.map(v => ((v % 10) + 10) % 10));
            const expanded = [];
            for (let n = 1; n <= maxBall; n++) {
                if (tailSet.has(n % 10)) expanded.push(n);
            }
            working = expanded;
        }
        return working;
    },

    /**
     * [DEPRECATED 2026-05-03] simulator_evaluator.js로 이전됨.
     * 두 배열 결합 연산 (ws1 op ws2) — broadcast 모드
     *
     * - union: 합집합 (left ∪ right)
     * - 산술 (+, -, *, /, %):
     *     · 둘 다 단일값: 단순 산술
     *     · 한쪽 단일값, 다른쪽 배열: broadcast (단일값을 모든 원소에 적용)
     *     · 같은 길이 배열: element-wise (i번째끼리)
     *     · 다른 길이 배열: cartesian (모든 조합)
     */
    _combineArrays: (left, right, op) => {
        if (op === 'union') {
            return [...left, ...right];
        }
        if (op === 'intersection') {
            const rightSet = new Set(right);
            return left.filter(v => rightSet.has(v));
        }
        if (op === 'difference') {
            const rightSet = new Set(right);
            return left.filter(v => !rightSet.has(v));
        }
        if (op === 'symdiff') {
            const leftSet = new Set(left);
            const rightSet = new Set(right);
            const out = [];
            for (const v of left) if (!rightSet.has(v)) out.push(v);
            for (const v of right) if (!leftSet.has(v)) out.push(v);
            return out;
        }
        const doOp = (x, y) => {
            switch (op) {
                case '+': return x + y;
                case '-': return x - y;
                case '*': return x * y;
                case '/': return y === 0 ? 0 : Math.floor(x / y);
                case '%': return y === 0 ? 0 : (x % y);
            }
            return x;
        };
        const L = left.length, R = right.length;
        if (L === 0 || R === 0) return [];
        if (L === 1 && R === 1) return [doOp(left[0], right[0])];
        if (L === 1) return right.map(v => doOp(left[0], v));    // broadcast left
        if (R === 1) return left.map(v => doOp(v, right[0]));    // broadcast right
        if (L === R) return left.map((v, i) => doOp(v, right[i])); // element-wise
        // 길이 다른 배열 → cartesian (모든 조합)
        const out = [];
        for (const a of left) for (const b of right) out.push(doOp(a, b));
        return out;
    },

    // ── DB selector (한국 chip + 해외 select) ────────────────────
    _bindDBSelector: () => {
        // 한국 chip
        const koreaChip = document.getElementById('db-chip-korea');
        if (koreaChip) {
            koreaChip.addEventListener('click', async () => {
                if (CustomSim.currentDB === 'korea') return;
                CustomSim._setActiveDB('korea');
                await CustomSim.loadDraws('korea');
            });
        }
        // 해외 select
        const sel = document.getElementById('db-select-overseas');
        if (sel) {
            sel.addEventListener('change', async (e) => {
                const id = e.target.value;
                if (!id) return;
                CustomSim._setActiveDB(id);
                await CustomSim.loadDraws(id);
            });
        }
    },

    _setActiveDB: (db) => {
        CustomSim.currentDB = db;
        const koreaChip = document.getElementById('db-chip-korea');
        const sel = document.getElementById('db-select-overseas');
        if (db === 'korea') {
            koreaChip?.classList.add('db-chip-active');
            if (sel) sel.value = '';
        } else {
            koreaChip?.classList.remove('db-chip-active');
        }
        // 메타 표시
        const metaEl = document.getElementById('db-meta');
        if (db === 'korea') {
            metaEl?.classList.add('hidden');
        } else {
            const lottery = CustomSim.lotteries.find(l => l.id === db);
            if (lottery && metaEl) {
                document.getElementById('db-meta-format').textContent = lottery.format || '6/45';
                document.getElementById('db-meta-bonus').textContent = lottery.bonus_count ?? 0;
                document.getElementById('db-meta-max').textContent = lottery.max_number ?? 45;
                metaEl.classList.remove('hidden');
            }
        }
    },

    _bindWindowSlider: () => {
        const slider = document.getElementById('windowSlider');
        const display = document.getElementById('windowDisplay');
        if (!slider || !display) return;
        slider.addEventListener('input', () => {
            CustomSim.windowN = parseInt(slider.value);
            display.textContent = CustomSim.windowN;
        });
    },

    // ── 동행복권 + 해외 데이터 로드 (S2 - 즉시) ──────────────────
    loadDraws: async (dbId) => {
        const listEl = document.getElementById('draws-list');
        const countEl = document.getElementById('draw-count-badge');
        if (!listEl || !countEl) return;

        // 스켈레톤 표시
        countEl.textContent = '로딩 중...';

        try {
            let draws = [];
            // [fix-259] 한국 로또 당첨번호 캐시 — 해외 로또 선택 시 비교 기준으로 사용
            // 사용자 의도: 해외 데이터로 수식 빌드 → 산출 결과를 한국 당첨번호와 비교
            if (!CustomSim.koreaDraws) {
                try {
                    const { data: kData } = await window.supabaseClient
                        .from('lotto_draws')
                        .select('round, date, numbers, bonus')
                        .order('round', { ascending: false });
                    CustomSim.koreaDraws = (kData || []).map(d => ({
                        drawNo:  d.round,
                        drawDate: d.date,
                        numbers: (d.numbers || []).slice().sort((a,b) => a - b),
                        bonus:   d.bonus,
                        maxBall: 45,
                    }));
                    // drawNo로 빠른 조회
                    CustomSim.koreaDrawByNo = {};
                    CustomSim.koreaDraws.forEach(d => { CustomSim.koreaDrawByNo[d.drawNo] = d; });
                } catch (e) { console.warn('[fix-259] korea draws cache 실패:', e); }
            }

            if (dbId === 'korea') {
                draws = CustomSim.koreaDraws ? [...CustomSim.koreaDraws] : [];
                draws.forEach(d => { d.dbId = 'korea'; });
            } else {
                // 해외 로또 (lotteries.id = UUID)
                const { data, error } = await window.supabaseClient
                    .from('draws')
                    .select('*')
                    .eq('lottery_id', dbId)
                    .order('draw_date', { ascending: false })
                    .range(0, 3000);
                if (error) throw error;
                const maxBall = CustomSim._getMaxBall(dbId);

                // [fix-303] overseas_lotto.html과 동일한 한국 회차 매핑 빌드
                // krDrawMap: 'YYYY-MM-DD' → { numbers, round }
                const krDrawMap = new Map();
                (CustomSim.koreaDraws || []).forEach(k => {
                    if (k.drawDate) krDrawMap.set(k.drawDate, { numbers: k.numbers || [], round: k.drawNo });
                });
                // 미추첨 회차 가상 추가 (latest+1, latest+2)
                if (CustomSim.koreaDraws && CustomSim.koreaDraws.length > 0) {
                    const latest = CustomSim.koreaDraws[0]; // koreaDraws는 desc 정렬 (최신 우선)
                    if (latest && latest.drawDate) {
                        const nextSat = new Date(latest.drawDate + 'T00:00:00');
                        nextSat.setDate(nextSat.getDate() + 7);
                        const nextDateStr = nextSat.toISOString().slice(0, 10);
                        if (!krDrawMap.has(nextDateStr)) {
                            krDrawMap.set(nextDateStr, { numbers: [], round: latest.drawNo + 1, _pending: true });
                        }
                        const nextSat2 = new Date(nextSat);
                        nextSat2.setDate(nextSat2.getDate() + 7);
                        const next2DateStr = nextSat2.toISOString().slice(0, 10);
                        if (!krDrawMap.has(next2DateStr)) {
                            krDrawMap.set(next2DateStr, { numbers: [], round: latest.drawNo + 2, _pending: true });
                        }
                    }
                }
                // 해외 추첨일 → 다음 토요일(±4일 허용) 매핑
                const findNearestKr = (dateStr) => {
                    if (!dateStr) return null;
                    const date = new Date(dateStr + 'T00:00:00');
                    const dow = date.getDay(); // 0=일,1=월,...6=토
                    const daysToSat = dow === 6 ? 7 : (6 - dow + 7) % 7 || 7;
                    const targetSat = new Date(date);
                    targetSat.setDate(targetSat.getDate() + daysToSat);
                    const refTime = targetSat.getTime();
                    const MAX = 4 * 86400000;
                    let best = null, bestDiff = Infinity;
                    for (const [d, draw] of krDrawMap) {
                        const diff = Math.abs(new Date(d + 'T00:00:00').getTime() - refTime);
                        if (diff <= MAX && diff < bestDiff) { bestDiff = diff; best = draw; }
                    }
                    return best;
                };

                // [fix-322] 옵션 C: 산출=해외 데이터 / 당첨번호 컬럼=한국 데이터 분리
                // - draws[i].numbers/bonus = 해외 원본 (시뮬레이션 입력, chip 산출 데이터)
                // - draws[i].korNumbers/korBonus/korDate = 한국 매핑 (당첨번호 컬럼·검증 대상)
                // - drawNo/round = 한국 매핑 회차 (라벨 + simulator_evaluator 호환)
                const koreaByRound = CustomSim.koreaDrawByNo || {};
                draws = (data || []).map(d => {
                    const kr = findNearestKr(d.draw_date);
                    const effectiveRound = kr ? kr.round : (d.draw_no || null);
                    const overseasNums = [d.n1, d.n2, d.n3, d.n4, d.n5, d.n6].filter(n => n != null).sort((a, b) => a - b);
                    const koreaRow = effectiveRound ? koreaByRound[effectiveRound] : null;
                    return {
                        drawNo:   effectiveRound,
                        round:    effectiveRound,
                        // 옵션 C: 해외 원본 데이터를 시뮬레이션 입력으로 사용 (산출 결과가 해외 번호 기반)
                        drawDate: d.draw_date,
                        numbers:  overseasNums,
                        bonus:    d.b1,
                        bonus2:   d.b2,
                        maxBall:  maxBall,
                        dbId,
                        // [fix-303/322] 한국 회차 매핑 — 매트릭스 당첨번호 컬럼·검증 비교용
                        korRound:   kr ? kr.round : null,
                        korNumbers: koreaRow ? (koreaRow.numbers || []).slice().sort((a, b) => a - b) : (kr ? (kr.numbers || []) : []),
                        korBonus:   koreaRow ? koreaRow.bonus : null,
                        korDate:    koreaRow ? koreaRow.drawDate : null,
                        korPending: kr ? !!kr._pending : false,
                        // 해외 원본 별도 보존 (덮어쓰기 방지)
                        overseasDrawNo:   d.draw_no || null,
                        overseasNumbers:  overseasNums,
                        overseasBonus:    d.b1,
                        overseasBonus2:   d.b2,
                        overseasDrawDate: d.draw_date,
                        overseasMaxBall:  maxBall,
                    };
                });
            }

            CustomSim.draws = draws;
            CustomSim.selectedRound = draws[0]?.drawNo || null;

            // 렌더
            CustomSim._renderDrawsList();

            countEl.textContent = `${draws.length.toLocaleString()}회차`;

            // 버튼 활성화
            // btn-run은 v5에서 제거됨 (전체 시뮬레이션 자동), btn-save만 활성화 제어
            const btnSave = document.getElementById('btn-save');
            if (btnSave) btnSave.disabled = draws.length === 0;

            // 미리보기 갱신
            if (typeof CustomSim.refreshPreview === 'function') {
                CustomSim.refreshPreview();
            }
        } catch (e) {
            console.error('[CustomSim v4] loadDraws Error:', e);
            listEl.innerHTML = `
                <div class="px-6 py-10 text-center">
                    <span class="material-symbols-outlined text-3xl text-slate-300 block mb-2">error</span>
                    <p class="meta">데이터 로드 실패: ${e.message}</p>
                </div>`;
            countEl.textContent = '오류';
        }
    },

    // ── 회차 리스트 렌더 (S2 - 가상 스크롤은 S11에서 강화) ──────
    _renderDrawsList: () => {
        const listEl = document.getElementById('draws-list');
        if (!listEl || CustomSim.draws.length === 0) return;

        // 끝수 모드 — 본번호/보너스 ball 표시값을 1자리(끝수)로 변환
        const isTailDisplay = CustomSim.dataMode === 'tails';

        // 회귀 간격 K (기본 1)
        const regSel = document.getElementById('draws-regression');
        const K = Math.max(1, parseInt(regSel?.value || '1') || 1);

        // K회귀 — 시뮬레이터 현재(simNow=DB최신+1) 기준
        // 예) simNow=1223, K=2 → 1221, 1219, 1217 …
        // 1223(예정) 행은 _renderDrawsList 시작부에서 별도 prepend됨
        // [fix-306] 해외 로또: drawNo가 korRound로 매핑됨 → 한국 simNow 기준 K회귀 정상 동작
        const isKoreaForK = CustomSim.currentDB === 'korea';
        const latestForK = CustomSim.draws[0];
        const koreaSimNow = (CustomSim.koreaDraws?.[0]?.drawNo || 0) + 1;
        const simNowForK = isKoreaForK
            ? ((latestForK?.drawNo || 0) + 1)
            : (koreaSimNow > 1 ? koreaSimNow : 0);
        const hasMappedRounds = CustomSim.draws.some(d => d.drawNo != null);
        let visible;
        if (simNowForK > 0 && hasMappedRounds) {
            // simNow - K * i (i=1, 2, 3, …) 순으로 매칭
            const drawByRound = new Map(CustomSim.draws.filter(d => d.drawNo != null).map(d => [d.drawNo, d]));
            visible = [];
            for (let i = 1; ; i++) {
                const targetRound = simNowForK - K * i;
                if (targetRound < 1) break;
                const d = drawByRound.get(targetRound);
                if (d) visible.push(d);
            }
        } else {
            // 해외 로또: 절대 회차 없음 → 인덱스 기반 fallback
            visible = CustomSim.draws.filter((d, idx) => idx % K === 0);
        }

        const isKorea = CustomSim.currentDB === 'korea';

        // ── 미추첨 다음 회차 (시뮬레이터의 "지금") placeholder ──
        // [fix-307 옵션 A] 한국 로또: 항상 prepend / 해외 로또: simNow에 매핑된 추첨 없을 때만 prepend
        let pendingRowHtml = '';
        let needPlaceholder = false;
        let simNow = 0;
        let nextDateStr = '';
        if (isKorea && CustomSim.draws.length > 0) {
            const latest = CustomSim.draws[0];
            simNow = (latest.drawNo || 0) + 1;
            if (latest.drawDate) {
                const dt = new Date(latest.drawDate);
                dt.setDate(dt.getDate() + 7);
                nextDateStr = dt.toISOString().slice(0, 10).replace(/-/g, '.');
            }
            needPlaceholder = true;
        } else if (!isKorea && CustomSim.draws.length > 0) {
            // 해외 모드: 한국 simNow를 기준으로 사용
            // [fix-309] 매핑된 해외 추첨이 있으면 그 row를 visible에 항상 포함 + placeholder 생략
            //   K회귀(K≥2) 사용 시 simNow가 visible에서 빠지면 placeholder가 잘못 표시되는 문제 해결
            const latestKor = CustomSim.koreaDraws?.[0];
            if (latestKor) {
                simNow = (latestKor.drawNo || 0) + 1;
                if (latestKor.drawDate) {
                    const dt = new Date(latestKor.drawDate);
                    dt.setDate(dt.getDate() + 7);
                    nextDateStr = dt.toISOString().slice(0, 10).replace(/-/g, '.');
                }
                // CustomSim.draws 전체에서 simNow에 매핑된 해외 row 검색 (visible 무관)
                const mappedSimNowRow = CustomSim.draws.find(d => d.drawNo === simNow);
                if (mappedSimNowRow) {
                    // K회귀로 visible에 빠졌어도 맨 앞에 prepend → 실제 당첨번호 표시 보장
                    if (!visible.some(d => d.drawNo === simNow)) {
                        visible = [mappedSimNowRow, ...visible];
                    }
                    needPlaceholder = false;  // 매핑된 추첨 있음 → placeholder(???) 안 표시
                } else {
                    needPlaceholder = simNow > 1;  // 매핑 없을 때만 placeholder
                }
            }
        }
        if (needPlaceholder && simNow > 0) {
            const placeholderBalls = Array(6).fill(0).map(() =>
                `<span class="ball ball-sm" style="background:#f1f5f9;color:#cbd5e1;box-shadow:none;">?</span>`
            ).join('');
            const placeholderBonus = `<span class="text-xs text-slate-300 mx-1">+</span><span class="ball ball-sm" style="background:#f1f5f9;color:#cbd5e1;box-shadow:none;">?</span>`;
            pendingRowHtml = `
                <div class="draw-row" data-round="pending" style="background:linear-gradient(135deg,#fef3c7 0%,#fff 60%);border-left:3px solid #f59e0b;">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-sm font-bold text-amber-700">${simNow}회 <span class="text-[10px] font-medium text-amber-500">(예정)</span></span>
                        <span class="meta text-amber-500">${nextDateStr}</span>
                    </div>
                    <div class="flex items-center gap-1 flex-wrap opacity-70">
                        ${placeholderBalls}
                        ${placeholderBonus}
                    </div>
                    <div class="flex items-center gap-1 mt-1.5 flex-wrap">
                        <span class="draw-chip draw-chip-rnd"
                            draggable="true" data-drag-type="round" data-drag-round="${simNow}" data-drag-digit-mode="ones"
                            title="드래그: 회차 일자리 (${simNow % 10})">회차일</span>
                        <span class="draw-chip draw-chip-rnd"
                            draggable="true" data-drag-type="round" data-drag-round="${simNow}" data-drag-digit-mode="tens"
                            title="드래그: 회차 십자리까지 (${simNow % 100})">회차십</span>
                        <span class="draw-chip draw-chip-rnd"
                            draggable="true" data-drag-type="round" data-drag-round="${simNow}" data-drag-digit-mode="hundreds"
                            title="드래그: 회차 백자리까지 (${simNow % 1000})">회차백</span>
                        <span class="draw-chip draw-chip-rnd"
                            draggable="true" data-drag-type="round" data-drag-round="${simNow}" data-drag-digit-mode="thousands"
                            title="드래그: 회차번호 전체 (${simNow})">회차</span>
                        <span class="draw-chip draw-chip-date"
                            draggable="true" data-drag-type="date" data-drag-date-part="year" data-drag-round="${simNow}"
                            title="드래그: 추첨년도 (${nextDateStr})">년</span>
                        <span class="draw-chip draw-chip-date"
                            draggable="true" data-drag-type="date" data-drag-date-part="month" data-drag-round="${simNow}"
                            title="드래그: 추첨월 (${nextDateStr})">월</span>
                        <span class="draw-chip draw-chip-date"
                            draggable="true" data-drag-type="date" data-drag-date-part="day" data-drag-round="${simNow}"
                            title="드래그: 추첨일 (${nextDateStr})">일</span>
                        <span class="text-[10px] text-amber-600 italic ml-1">미추첨 — 당첨번호 없음</span>
                    </div>
                </div>
            `;
        }

        listEl.innerHTML = pendingRowHtml + visible.map((d, idx) => {
            const dateStr = d.drawDate ? new Date(d.drawDate).toISOString().slice(0, 10).replace(/-/g, '.') : '';
            // 끝수 모드: 본번호/보너스 ball에 끝수만 표시 (1자리)
            const fmtBall = (n) => isTailDisplay ? `${n % 10}` : String(n).padStart(2, '0');
            const ballsHtml = d.numbers.map(n =>
                `<span class="ball ball-sm ${CustomSim._ballColor(n)}" title="${n}">${fmtBall(n)}</span>`
            ).join('');
            // 보너스볼: 번호대별 색상 + 'B' 배지 (ball-bonus 는 배지만)
            const bonusHtml = d.bonus
                ? `<span class="ball ball-sm ${CustomSim._ballColor(d.bonus)} ball-bonus" title="${d.bonus}">${fmtBall(d.bonus)}</span>`
                : '';
            const bonus2Html = d.bonus2
                ? `<span class="ball ball-sm ${CustomSim._ballColor(d.bonus2)} ball-bonus" title="${d.bonus2}">${fmtBall(d.bonus2)}</span>`
                : '';
            // [fix-303] 해외 로또: korRound가 매핑되어 있으면 한국 회차 표시 (overseas_lotto.html과 동일 매핑)
            // 한국: NNNN회, 해외(매핑됨): NNNN회 ⓚ, 해외(매핑 실패): #N (해외 자체 draw_no)
            let roundLabel;
            if (isKorea) {
                roundLabel = `${d.drawNo}회`;
            } else if (d.korRound) {
                const pendingMark = d.korPending ? ' <span class="text-[9px] text-amber-500">(예정)</span>' : '';
                roundLabel = `${d.korRound}회 <span class="text-[9px] text-slate-400 font-medium">ⓚ</span>${pendingMark}`;
            } else {
                roundLabel = d.drawNo ? `#${d.drawNo}` : '-';
            }
            const rowKey = isKorea ? d.drawNo : (d.korRound || `idx-${idx}`);
            const isActive = isKorea
                ? (d.drawNo === CustomSim.selectedRound)
                : (CustomSim.selectedRound === (d.korRound || `idx-${idx}`));

            // v5 — 카테고리별 drag chip (전라인 / 1~6라인 / 보너스 / 회차 / 일자)
            const posChips = [1, 2, 3, 4, 5, 6].map(p =>
                `<span class="draw-chip draw-chip-pos"
                    draggable="true" data-drag-type="pos" data-drag-pos="${p}" data-drag-round="${rowKey}"
                    title="드래그: 정렬 ${p}번째 본번호">${p}라인</span>`
            ).join('');
            const dragChips = `
                <div class="flex items-center gap-1 mt-1.5 flex-wrap">
                    <span class="draw-chip draw-chip-line"
                        draggable="true" data-drag-type="line" data-drag-round="${rowKey}"
                        title="드래그: 6 본번호 전체 (전라인)">전라인</span>
                    ${posChips}
                    ${d.bonus ? `<span class="draw-chip draw-chip-bonus"
                        draggable="true" data-drag-type="bonus" data-drag-round="${rowKey}"
                        title="드래그: 보너스볼">보너스</span>` : ''}
                    <span class="draw-chip draw-chip-rnd"
                        draggable="true" data-drag-type="round" data-drag-round="${rowKey}" data-drag-digit-mode="ones"
                        title="드래그: 회차 일자리 (${isKorea && d.drawNo != null ? d.drawNo % 10 : ''})">회차일</span>
                    <span class="draw-chip draw-chip-rnd"
                        draggable="true" data-drag-type="round" data-drag-round="${rowKey}" data-drag-digit-mode="tens"
                        title="드래그: 회차 십자리까지 (${isKorea && d.drawNo != null ? d.drawNo % 100 : ''})">회차십</span>
                    <span class="draw-chip draw-chip-rnd"
                        draggable="true" data-drag-type="round" data-drag-round="${rowKey}" data-drag-digit-mode="hundreds"
                        title="드래그: 회차 백자리까지 (${isKorea && d.drawNo != null ? d.drawNo % 1000 : ''})">회차백</span>
                    <span class="draw-chip draw-chip-rnd"
                        draggable="true" data-drag-type="round" data-drag-round="${rowKey}" data-drag-digit-mode="thousands"
                        title="드래그: 회차번호 전체 (${d.drawNo ?? ''})">회차</span>
                    <span class="draw-chip draw-chip-date"
                        draggable="true" data-drag-type="date" data-drag-date-part="year" data-drag-round="${rowKey}"
                        title="드래그: 추첨년도 (yyyy)">년</span>
                    <span class="draw-chip draw-chip-date"
                        draggable="true" data-drag-type="date" data-drag-date-part="month" data-drag-round="${rowKey}"
                        title="드래그: 추첨월 (1~12)">월</span>
                    <span class="draw-chip draw-chip-date"
                        draggable="true" data-drag-type="date" data-drag-date-part="day" data-drag-round="${rowKey}"
                        title="드래그: 추첨일 (1~31)">일</span>
                </div>
            `;

            // 개별 번호 drag (개별 모드 시에만 활성) — 끝수 모드 시 표시값도 끝수
            const individualBalls = d.numbers.map(n =>
                `<span class="ball ball-sm ${CustomSim._ballColor(n)} draw-num-drag"
                    ${CustomSim.selectionMode === 'num' ? `draggable="true" data-drag-type="num" data-drag-round="${rowKey}" data-drag-num="${n}"` : ''}
                    style="${CustomSim.selectionMode === 'num' ? 'cursor:grab;' : ''}" title="${n}">${fmtBall(n)}</span>`
            ).join('');

            const bonusHtml2 = d.bonus
                ? `<span class="ball ball-sm ${CustomSim._ballColor(d.bonus)} ball-bonus" title="${d.bonus}">${fmtBall(d.bonus)}</span>`
                : '';
            const bonus2Html2 = d.bonus2
                ? `<span class="ball ball-sm ${CustomSim._ballColor(d.bonus2)} ball-bonus" title="${d.bonus2}">${fmtBall(d.bonus2)}</span>`
                : '';

            return `
                <div class="draw-row ${isActive ? 'active' : ''}" data-round="${rowKey}">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-sm font-bold text-slate-900">${roundLabel}</span>
                        <span class="meta">${dateStr}</span>
                    </div>
                    <div class="flex items-center gap-1 flex-wrap">
                        ${CustomSim.selectionMode === 'num' ? individualBalls : ballsHtml}
                        ${bonusHtml2 ? `<span class="text-xs text-slate-300 mx-1">+</span>${bonusHtml2}` : ''}
                        ${bonus2Html2}
                    </div>
                    ${dragChips}
                </div>
            `;
        }).join('');

        // 회차 클릭 → 미리보기 기준 갱신
        listEl.querySelectorAll('.draw-row').forEach(row => {
            row.addEventListener('click', () => {
                const raw = row.dataset.round;
                if (raw === 'pending') return; // 미추첨 행 클릭 무시
                // 한국은 정수 회차, 해외는 'idx-N' 문자열
                CustomSim.selectedRound = isKorea ? parseInt(raw) : raw;
                listEl.querySelectorAll('.draw-row').forEach(r => r.classList.remove('active'));
                row.classList.add('active');
                if (typeof CustomSim.refreshPreview === 'function') {
                    CustomSim.refreshPreview();
                }
            });
        });
    },

    // ── (폐기) 끝수 0~9 패널 — 새 끝수 표시 모드로 대체 ────────────────
    // 끝수 모드는 dataMode='tails' 상태에서 _renderDrawsList가 본번호를 끝수 ball로 표시
    // 드롭 시 자동으로 ws.mode='tail' 활성화 → 산출값 % 10 + expand

    // ── 해외 로또 목록 로드 + 드롭다운 채우기 (overseas_lotto.html과 동일) ──
    _loadLotteriesAndPopulate: async () => {
        try {
            const { data, error } = await window.supabaseClient
                .from('lotteries')
                .select('*')
                .eq('is_active', true)
                .order('country', { ascending: true })
                .order('name', { ascending: true });
            if (error) throw error;

            CustomSim.lotteries = data || [];
            const sel = document.getElementById('db-select-overseas');
            if (!sel) return;

            // 국가별 그룹
            const grouped = {};
            CustomSim.lotteries.forEach(l => {
                if (!grouped[l.country]) grouped[l.country] = [];
                grouped[l.country].push(l);
            });

            sel.innerHTML = '<option value="">해외 로또 선택...</option>';
            Object.entries(grouped).forEach(([country, list]) => {
                const grp = document.createElement('optgroup');
                grp.label = `${CustomSim.COUNTRY_FLAGS[country] || ''} ${CustomSim.COUNTRY_NAMES[country] || country}`;
                list.forEach(l => {
                    const opt = document.createElement('option');
                    opt.value = l.id;
                    opt.textContent = l.name;
                    grp.appendChild(opt);
                });
                sel.appendChild(grp);
            });
            console.log(`[CustomSim] 해외 로또 ${CustomSim.lotteries.length}종 로드`);
        } catch (e) {
            console.warn('[CustomSim] 해외 로또 로드 실패 (한국만 사용):', e.message);
        }
    },

    _getMaxBall: (id) => {
        if (id === 'korea') return 45;
        const l = CustomSim.lotteries.find(x => x.id === id);
        return l?.max_number || 45;
    },

    // ── ball 색상 (1-10 노랑 / 11-20 파랑 / 21-30 빨강 / 31-40 회색 / 41-45 초록) ──
    _ballColor: (n) => {
        if (n <= 10) return 'ball-y';
        if (n <= 20) return 'ball-b';
        if (n <= 30) return 'ball-r';
        if (n <= 40) return 'ball-gr';
        return 'ball-g';
    },

    // ============================================================
    // 핵심 연산 로직 (기존 보존) — S4-S6에서 확장
    // ============================================================

    /**
     * 보정 로직: 0 → null / 음수 → 역산 / 초과 → 순환
     */
    normalize: (val, maxBall) => {
        if (val === 0) return null;
        if (val < 0) {
            val = maxBall + (val % maxBall);
            if (val === 0) return null;
        }
        if (val > maxBall) {
            val = ((val - 1) % maxBall) + 1;
        }
        return val;
    },

    // ── Loading overlay ─────────────────────────────────────────
    showLoading: (show) => {
        const o = document.getElementById('loading-overlay');
        if (o) o.classList.toggle('hidden', !show);
    },

    // ============================================================
    // Stage 6-F-X: Formula Variable Sweep (Phase 5)
    // ============================================================

    /**
     * 변수 토글 ($) — transform의 isVariable 플래그 전환
     */
    _onVarToggle: (wsId, transformIdx) => {
        const ws = CustomSim.workspaces.find(w => w.id === wsId);
        if (!ws) return;

        const tx = ws.transforms[transformIdx];
        if (!tx) return;

        tx.isVariable = !tx.isVariable;

        // 변수 1개 이상 있으면 "Sweep 실행" 버튼 활성화
        const hasVar = CustomSim.workspaces.some(w =>
            w.transforms.some(t => t.isVariable)
        );
        document.getElementById('btn-sweep-run').disabled = !hasVar;

        // 변수 개수 표시
        const varCount = CustomSim.workspaces.reduce((sum, w) =>
            sum + w.transforms.filter(t => t.isVariable).length, 0
        );
        document.getElementById('sweep-var-count').textContent = `(변수 ${varCount}개)`;

        CustomSim._renderWorkspaces();
        CustomSim._save();
    },

    /**
     * v5-multi 산식 직렬화 (Sweep API 요청용)
     */
    _serializeFormula: () => {
        return {
            version: 'v5-multi',
            workspaces: CustomSim.workspaces.map(ws => ({
                id: ws.id,
                label: ws.label,
                cards: ws.cards.map(c => ({ ...c })),  // shallow copy
                transforms: ws.transforms.map(t => ({
                    op: t.op,
                    value: t.value,
                    isVariable: !!t.isVariable
                })),
                mode: ws.mode,
                hiddenInOutput: !!ws.hiddenInOutput,
                setOpOverride: ws.setOpOverride ? { ...ws.setOpOverride } : null,
            })),
            combineOps: CustomSim.combineOps.map(co => ({ ...co })),
            combinePostTransforms: CustomSim.combinePostTransforms.map(t => ({
                op: t.op,
                value: t.value
            })),
            combinePostExpand: !!CustomSim.combinePostExpand,
        };
    },

    /**
     * 변수 경로 추출 (isVariable=true인 transform 위치)
     */
    _findVariablePaths: () => {
        const paths = [];
        for (const ws of CustomSim.workspaces) {
            ws.transforms.forEach((t, idx) => {
                if (t.isVariable) {
                    paths.push({
                        ws_id: ws.id,
                        transform_idx: idx,
                        field: 'value'
                    });
                }
            });
        }
        return paths;
    },

    /**
     * Sweep 모달 열기
     */
    _openSweepModal: () => {
        const paths = CustomSim._findVariablePaths();
        if (paths.length === 0) {
            alert('변수가 없습니다. 변환 칩의 $ 버튼을 클릭하여 변수를 지정하세요.');
            return;
        }

        // 변수 위치 표시 (첫 변수만)
        const first = paths[0];
        const ws = CustomSim.workspaces.find(w => w.id === first.ws_id);
        const wsLabel = ws ? ws.label : first.ws_id;
        document.getElementById('sweep-var-path').textContent =
            `${wsLabel} 변환 #${first.transform_idx + 1}`;

        document.getElementById('sweep-modal-overlay').style.display = 'flex';
    },

    /**
     * Sweep 모달 닫기
     */
    _closeSweepModal: () => {
        document.getElementById('sweep-modal-overlay').style.display = 'none';
    },

    /**
     * Sweep 실행 API 호출
     */
    _runSweep: async () => {
        const formula = CustomSim._serializeFormula();
        const variable_paths = CustomSim._findVariablePaths();
        const variable_range = {
            min: parseInt(document.getElementById('sweep-min').value),
            max: parseInt(document.getElementById('sweep-max').value),
            step: parseInt(document.getElementById('sweep-step').value),
        };
        const criteria = {
            min_consecutive: parseInt(document.getElementById('sweep-min-consec').value),
            include_bonus: document.getElementById('sweep-include-bonus').checked,
            min_avg_gap: parseFloat(document.getElementById('sweep-min-gap').value),
        };

        // 모달 닫기
        CustomSim._closeSweepModal();

        // 진행률 표시
        document.getElementById('sweep-running').style.display = 'block';

        try {
            const _sweepBase = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
            const res = await fetch(`${_sweepBase}/api/sweep/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    formula,
                    variable_paths,
                    variable_range,
                    criteria,
                }),
            });

            const data = await res.json();
            const job_id = data.job_id;

            // 진행률 폴링
            CustomSim._pollSweepProgress(job_id);
        } catch (e) {
            console.error('[Sweep] API Error:', e);
            alert('Sweep 실행 실패: ' + e.message);
            document.getElementById('sweep-running').style.display = 'none';
        }
    },

    /**
     * Sweep 진행률 폴링 (2초 간격)
     */
    _pollSweepProgress: async (job_id) => {
        const poll = async () => {
            try {
                const _sweepBase = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
                const res = await fetch(`${_sweepBase}/api/sweep/${job_id}/status`);
                const data = await res.json();

                const { status, progress } = data;
                const { current, total, eta_seconds } = progress;

                // 진행률 갱신
                const pct = total > 0 ? Math.round((current / total) * 100) : 0;
                document.getElementById('sweep-progress-text').textContent =
                    `${current}/${total}`;
                document.getElementById('sweep-progress-fill').style.width = `${pct}%`;

                // ETA 표시
                const eta = eta_seconds
                    ? `${Math.round(eta_seconds)}초`
                    : '--';
                document.getElementById('sweep-eta').textContent = eta;

                // complete 시 결과 렌더
                if (status === 'complete') {
                    document.getElementById('sweep-running').style.display = 'none';
                    await CustomSim._renderSweepResults(job_id);
                    return;
                }

                // failed 시 에러 표시
                if (status === 'failed') {
                    document.getElementById('sweep-running').style.display = 'none';
                    alert('Sweep 실행 실패');
                    return;
                }

                // 2초 후 재폴링
                setTimeout(poll, 2000);
            } catch (e) {
                console.error('[Sweep Poll] Error:', e);
                document.getElementById('sweep-running').style.display = 'none';
            }
        };

        poll();
    },

    /**
     * Sweep 결과 렌더링 (Phase 6 상세 구현)
     */
    _renderSweepResults: async (job_id) => {
        try {
            const _sweepBase = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
            const res = await fetch(`${_sweepBase}/api/sweep/${job_id}/results?min_consecutive=3&limit=500`);
            const data = await res.json();

            const { results, total } = data;

            // 그룹핑 (5/4/3연속)
            const by_consec = { 5: [], 4: [], 3: [] };
            for (const r of results) {
                const k = Math.min(r.max_consecutive, 5);
                if (k >= 3) by_consec[k].push(r);
            }

            // 결과 섹션 표시
            document.getElementById('sweep-total-results').textContent = total;
            document.getElementById('sweep-results-section').style.display = 'block';

            // 결과 그룹 렌더링
            const container = document.getElementById('sweep-results-groups');
            container.innerHTML = `
                <div class="mb-8">
                    <h4 class="text-sm font-semibold text-gray-700 mb-3">
                        5연속 hit 산식 <span class="text-xs font-normal text-gray-500">${by_consec[5].length}건</span>
                    </h4>
                    <div id="sweep-5-list" class="space-y-2"></div>
                </div>
                <div class="mb-8">
                    <h4 class="text-sm font-semibold text-gray-700 mb-3">
                        4연속 hit 산식 <span class="text-xs font-normal text-gray-500">${by_consec[4].length}건</span>
                    </h4>
                    <div id="sweep-4-list" class="space-y-2"></div>
                </div>
                <div class="mb-8">
                    <h4 class="text-sm font-semibold text-gray-700 mb-3">
                        3연속 hit 산식 <span class="text-xs font-normal text-gray-500">${by_consec[3].length}건</span>
                    </h4>
                    <div id="sweep-3-list" class="space-y-2"></div>
                </div>
            `;

            // 각 그룹 카드 렌더
            CustomSim._renderSweepCardList('sweep-5-list', by_consec[5], job_id);
            CustomSim._renderSweepCardList('sweep-4-list', by_consec[4], job_id);
            CustomSim._renderSweepCardList('sweep-3-list', by_consec[3], job_id);
        } catch (e) {
            console.error('[Sweep Results] Error:', e);
        }
    },

    /**
     * Sweep 결과 카드 목록 렌더링
     */
    _renderSweepCardList: (containerId, results, job_id) => {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (results.length === 0) {
            container.innerHTML = '<div class="text-xs text-gray-400 italic">결과 없음</div>';
            return;
        }

        container.innerHTML = results.map(r => {
            // target_numbers 렌더 (ball)
            const targets = r.target_numbers || [];
            const targetBalls = targets.slice(0, 10).map(n => {
                const color = CustomSim._ballColor(n);
                return `<span class="ball ball-sm ${color}">${n}</span>`;
            }).join('');

            return `
                <div class="sweep-card" data-job-id="${job_id}" data-var-value="${r.variable_value}">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-xs text-gray-500">
                            var = <span class="font-mono font-semibold text-gray-800" style="font-feature-settings: 'tnum'">${r.variable_value}</span>
                        </span>
                        <span class="text-xs text-gray-500">평균 ${r.avg_gap_rounds.toFixed(1)}회 간격</span>
                    </div>
                    <div class="target-numbers flex flex-wrap gap-1.5 mb-2">
                        ${targetBalls}
                        ${targets.length > 10 ? `<span class="text-xs text-gray-400">+${targets.length - 10}</span>` : ''}
                    </div>
                    <div class="flex items-center justify-between text-xs text-gray-500">
                        <span>${r.hit_count} hit / ${r.max_consecutive}연속</span>
                        <button class="btn-history text-blue-500 hover:underline" data-job-id="${job_id}" data-var-value="${r.variable_value}">
                            과거 통계 ▶
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // 과거 통계 버튼 이벤트 바인딩
        container.querySelectorAll('.btn-history').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const jid = e.target.dataset.jobId;
                const vval = e.target.dataset.varValue;
                CustomSim._openHistoryModal(jid, vval);
            });
        });
    },

    /**
     * 과거 통계 모달 열기 (Phase 6)
     */
    _openHistoryModal: async (job_id, variable_value) => {
        try {
            const _sweepBase = (window.LANGCHAIN_CONFIG && window.LANGCHAIN_CONFIG.URL) || 'http://127.0.0.1:8000';
            const res = await fetch(`${_sweepBase}/api/sweep/${job_id}/results/${variable_value}/history`);
            const data = await res.json();

            // 모달 렌더 (간단한 alert 대신 HTML 모달 구현 가능)
            // 여기서는 console로 출력
            console.log('[History Modal]', data);
            alert(`var=${variable_value}\n최장 연속: ${data.max_consecutive}\n총 hit: ${data.hit_count}\n평균 간격: ${data.avg_gap_rounds.toFixed(1)}`);
        } catch (e) {
            console.error('[History Modal] Error:', e);
            alert('과거 통계 조회 실패');
        }
    },

    /**
     * Sweep 버튼/모달 이벤트 바인딩
     */
    _bindSweepEvents: () => {
        const btnRun = document.getElementById('btn-sweep-run');
        const btnCancel = document.getElementById('btn-sweep-cancel');
        const btnStart = document.getElementById('btn-sweep-start');

        if (btnRun) {
            btnRun.addEventListener('click', () => {
                CustomSim._openSweepModal();
            });
        }

        if (btnCancel) {
            btnCancel.addEventListener('click', () => {
                CustomSim._closeSweepModal();
            });
        }

        if (btnStart) {
            btnStart.addEventListener('click', () => {
                CustomSim._runSweep();
            });
        }
    },
};

window.CustomSim = CustomSim;
