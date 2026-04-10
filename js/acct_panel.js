/**
 * AcctPanel - 계정 설정 / 텔레그램 Chat ID 패널
 * layout.js에서 헤더 주입 후 동적 로드됨
 */
window.AcctPanel = (() => {
    let open = false;

    function toggle() {
        open = !open;
        const panel = document.getElementById('acct-panel');
        if (!panel) return;
        if (open) {
            panel.classList.remove('hidden');
            requestAnimationFrame(() => {
                panel.style.opacity = '1';
                panel.style.transform = 'scale(1)';
            });
            refresh();
        } else {
            _close();
        }
    }

    function _close() {
        open = false;
        const panel = document.getElementById('acct-panel');
        if (!panel) return;
        panel.style.opacity = '0';
        panel.style.transform = 'scale(0.95)';
        setTimeout(() => panel.classList.add('hidden'), 150);
    }

    function refresh() {
        const chatId  = localStorage.getItem('telegram_chat_id') || '';
        const curEl   = document.getElementById('tg-current');
        const curVal  = document.getElementById('tg-current-val');
        const sBadge  = document.getElementById('tg-status-badge');
        const dotBadge= document.getElementById('tg-badge');
        const inputArea = document.getElementById('tg-input-area'); // [추가] 입력 영역 wrapper
        const input = document.getElementById('tg-chat-input');

        if (chatId) {
            if (curEl)  { curEl.classList.remove('hidden'); curEl.style.display = 'flex'; }
            if (curVal) curVal.textContent = 'Chat ID: ' + chatId;
            if (sBadge) sBadge.classList.remove('hidden');
            if (dotBadge) dotBadge.classList.remove('hidden');
            
            // [수정] 이미 등록된 경우 입력 필드 초기화 및 입력 영역 숨김
            if (input) input.value = '';
            if (inputArea) inputArea.classList.add('hidden');
        } else {
            if (curEl)    curEl.classList.add('hidden');
            if (sBadge)   sBadge.classList.add('hidden');
            if (dotBadge) dotBadge.classList.add('hidden');
            
            // [수정] 등록되지 않은 경우 입력 영역 다시 표시
            if (inputArea) inputArea.classList.remove('hidden');
        }
    }

    function saveTg() {
        const val = (document.getElementById('tg-chat-input')?.value || '').trim();
        if (!val) { alert('Chat ID를 입력해주세요.'); return; }
        if (!/^-?\d+$/.test(val)) {
            alert('Chat ID는 숫자만 입력해주세요.\n예: 123456789\n그룹 채널은 -로 시작합니다.');
            return;
        }
        localStorage.setItem('telegram_chat_id', val);
        refresh();
    }

    function clearTg() {
        if (!confirm('텔레그램 Chat ID를 삭제할까요?')) return;
        localStorage.removeItem('telegram_chat_id');
        const input = document.getElementById('tg-chat-input');
        if (input) input.value = '';
        refresh();
    }

    // 패널 외부 클릭 → 닫기
    document.addEventListener('click', e => {
        if (open && !document.getElementById('loginBtn')?.contains(e.target)) {
            _close();
        }
    });

    // 헤더가 주입된 직후 호출되므로 바로 refresh
    setTimeout(refresh, 50);

    return { toggle, saveTg, clearTg, refresh };
})();
