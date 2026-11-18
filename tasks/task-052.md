# task-052 언어 탭 화면

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-049 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | builder |
| 근거 | `docs/03_SCREENS_UX.md` 언어 탭·F-07, `design/spec.json` |
| 쓰기 허용 | `apps/web/src/app/(app)/production/**`, `apps/web/src/components/production/**`, 테스트 |

## 할 것
- 편집 화면 공통 ko·ja 탭, "일본어판 만들기"→번역 초안→수정, ja는 컷 잠금, PROD-03 언어별 결과·게시 문구.

## 하지 않을 것
- API 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] web test·lint·typecheck 통과
