# DESIGN.md — Nomadroom-Studio

> 정답은 `apps/web/src/styles/tokens.css`. 값 표는 `docs/DESIGN_TOKENS.md`(design-preview --md 생성)를 본다. 이 문서에는 값을 복사하지 않는다.
> 비주얼 수치의 최종 확정은 사람이 한다(현재 값은 시안에서 옮긴 후보).

## 1. 브리프
- 대상: 방 꾸미기·공간 구성을 검토하는 개인 사용자(데스크톱 중심, 모바일 열람).
- 주된 일: 후보 비교·선택, 지표 확인, 프로필·설정 관리 (대시보드).
- 분위기: 차분함 · 신뢰 · 정돈됨 (짙은 녹색 + 옅은 민트 면).
- 피할 것: 원색 강조 남발, 장식 그림자, 촘촘한 작은 글자(12px 미만), 색만으로 상태 구분.
- 시안 근거: `docs/design/screenshots/dashboard-1440.png`.

## 2. 토큰 사용 규칙
- 컴포넌트에 hex·px 직접 쓰기 금지. Tailwind 유틸(`bg-surface`, `text-muted`, `rounded-control`)이나 `var(--…)`만 쓴다.
- 짝: `--color-X` 위 글자는 `--color-X-fg`, `*-soft` 위 글자는 `*-soft-fg`. 페이지는 `bg` 위에 `surface` 면을 올린다.
- 입력창·체크박스 경계는 `--color-input`(3:1), 장식 구분선만 `--color-border`.
- 포커스 링: `--color-ring` 2px, offset 3px(대비 4.0~4.3:1 수동 계산, 기준 3:1 통과; --check 표에는 ring 짝이 없음). 모든 상호작용 요소에 보임. `prefers-reduced-motion` 존중.
- 글자: 제목 `--text-h1/h2`, 본문 `--text-body`, 보조 `--text-caption`. 숫자·금액은 `--font-mono` 또는 tabular-nums.
- 반응형 접두사는 `tablet:`(768~)·`desktop:`(1200~)만 쓴다(sm/md/lg 비활성). 시안의 max-width 510/780/1100 대신 3구간(767/1199)을 쓴다.
- 글꼴·간격 토큰은 rem(1rem=16px, 값 옆 주석·토큰 표에 px 환산). 입력 글자는 `--text-input`(16px)로 iOS 확대를 막는다. 모바일 body 15px, 태블릿·데스크톱 14px.
- 반응형 3구간: ~767 / 768~1199 / 1200~. 폰트 표는 `docs/DESIGN_TOKENS.md`. 구간별 레이아웃은 모바일 1열·카드 1열, 태블릿 사이드바 좁게, 데스크톱 사이드바 + 카드 2열.
- 다크: `.dark` 클래스가 같은 이름의 토큰을 덮어쓴다. 컴포넌트는 분기하지 않는다.
- 변경은 토큰 한 줄로: 예 `--radius-control` 값만 바꾼다.

## 3. 컴포넌트 기본 (토큰 이름만 표기)
| 컴포넌트 | 배경 · 글자 · 경계 | 반경 | 상태 |
|---|---|---|---|
| 버튼(기본) | surface · text · border | control | hover 경계 강조, disabled 불투명 55% |
| 버튼(primary) | primary · primary-fg | control | hover primary-hover |
| 버튼(bare) | 투명 · text | control | hover primary-soft |
| 태그 | primary-soft · primary-soft-fg, 변형 neutral-soft / warning-soft | chip | 12px(caption) 굵게, 점(dot) 선택 |
| 칩(필터) | surface · text-muted · border | chip | 선택(aria-pressed) primary · primary-fg |
| 패널 | surface · text · border, 안쪽 간격 `spacing` 4.5~5배 | panel | 그림자 없음(필요 시 shadow-card) |
| 카드(후보) | surface · border, 썸네일 + 본문 + 하단 구분선 푸터 | card | 빈 상태는 점선 border + text-muted |
| 입력 | surface · text(`--text-input`) · input 경계 | control | focus ring |
| 내비 항목 | 투명 · text-muted | control | hover·선택 primary-soft · primary-soft-fg |

## 4. 상태 색
성공 `success`, 경고 `warning`, 중립(회색) `neutral-soft`, 오류 `danger`(옅은 면 `danger-soft`). 상태는 색 + 텍스트/점으로 함께 표시한다.
