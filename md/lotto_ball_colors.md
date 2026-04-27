# 로또 번호대별 표준 색상 가이드 (Lotto Number Band Colors)

로또랩 프로젝트에서 공통적으로 사용되는 번호대별 색상 정의입니다. `combination_generator.html`의 디자인을 표준으로 합니다.

| 번호대 | 색상 종류 | 그라데이션 시작 (#) | 그라데이션 끝 (#) | 클래스명 |
| :--- | :--- | :--- | :--- | :--- |
| **1 ~ 10** | 노란색 (Yellow) | `#f59e0b` | `#d97706` | `.ball-y` |
| **11 ~ 20** | 파란색 (Blue) | `#3b82f6` | `#2563eb` | `.ball-b` |
| **21 ~ 30** | 빨간색 (Red) | `#ef4444` | `#dc2626` | `.ball-r` |
| **31 ~ 40** | 회색 (Gray) | `#6b7280` | `#4b5563` | `.ball-g` |
| **41 ~ 45** | 초록색 (Green) | `#10b981` | `#059669` | `.ball-gr` |

## CSS 구현 가이드

```css
/* 로또 공 기본 공통 스타일 */
.ball {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    font-size: 13px;
    font-weight: 500;
    color: #fff;
    flex-shrink: 0;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.12);
}

/* 번호대별 색상 클래스 */
.ball-y  { background: linear-gradient(135deg, #f59e0b, #d97706); } /* 1-10 */
.ball-b  { background: linear-gradient(135deg, #3b82f6, #2563eb); } /* 11-20 */
.ball-r  { background: linear-gradient(135deg, #ef4444, #dc2626); } /* 21-30 */
.ball-g  { background: linear-gradient(135deg, #6b7280, #4b5563); } /* 31-40 */
.ball-gr { background: linear-gradient(135deg, #10b981, #059669); } /* 41-45 */
```

## Javascript 매핑 로직

```javascript
/**
 * 번호에 따른 공 색상 클래스 반환
 * @param {number} n 로또 번호 (1-45)
 */
function getBallColor(n) {
    if (n <= 10) return 'ball-y';
    if (n <= 20) return 'ball-b';
    if (n <= 30) return 'ball-r';
    if (n <= 40) return 'ball-g';
    return 'ball-gr';
}
```
