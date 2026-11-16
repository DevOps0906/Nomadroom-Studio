# task-018 공통 레이아웃(앱 셸)

| 항목 | 내용 |
|---|---|
| 웨이브 | W1 |
| 선행 | task-001 |
| 위험도 | 낮음 |
| 보안 영향 | 없음 (외부 링크는 새 탭 `rel="noopener noreferrer"`) |
| 담당 | builder (+ codex-reviewer design) |
| 근거 | `docs/design/Nomadroom_Dashboard_Design.html`(사이드바·상단 바·작업 탭), `docs/03_SCREENS_UX.md` 공통 레이아웃 비고, 환경변수 `NEXT_PUBLIC_OPS_SITE_URL` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/layout.tsx`, `apps/web/src/components/shell/**`, `.env.example`(이름만) |

## 할 것
- 사이드바(브랜드·"＋ 새 영상 만들기"·메뉴·운영 화면/설정 링크), 상단 바(빵부스러기·작업 탭: 대시보드 · 주제 발굴↗ · 소재수집(정체))를 공통 레이아웃 컴포넌트로 만든다.
- 외부 링크는 `NEXT_PUBLIC_OPS_SITE_URL` 기준, 새 탭·↗ 표시. 내부 메뉴는 대시보드·소재수집(정체)만.
- 반응형 3구간: ~767 햄버거 드로어·작업 탭 가로 스크롤 칩, 768~1199 아이콘 레일, 1200~ 펼침. 색·크기는 토큰만.
- 셸 안 본문은 빈 슬롯(화면 내용은 012~016이 채운다).

## 하지 않을 것
- 화면별 본문·데이터 호출, 로그인·세션 처리(task-012), 메뉴 화면 내재화.

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm typecheck` 통과
- [x] `~/.claude/nomad/bin/shot`으로 3구간 캡처 확인(시안과 사이드바·탭 비교)
