# task-037 PROD-01 형식 선택 + PROD-02 예능형 패널

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-035 |
| 위험도 | 보통 |
| 보안 영향 | 없음(기존 API 사용) |
| 담당 | builder |
| 근거 | spec `PROD-01`·`PROD-02V`·`MON-01`·`PROD-00`(`design/spec.json`), `docs/03_SCREENS_UX.md` |
| 쓰기 허용 | `apps/web/src/app/(app)/production/**`, `apps/web/src/components/production/**`, MON-01 제작 버튼 파일, 해당 테스트 |

## 할 것
- PROD-01 맨 위 형식 선택(준비 시작 후 잠금). MON-01·PROD-00 진입 버튼을 "내부 제작"으로 통합.
- PROD-02 예능형 패널: 컷 리스트(순서 이동·src in/out·배율·x·y·시트 썸네일), 출력 타임라인 바, 대사 자막(line/punch), 반응 자막(x·y), 제목 1~2줄. 반응형 3구간.

## 하지 않을 것
- 카테고리형 패널 동작 변경, 영상 미리보기 플레이어(P0 제외), API 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `corepack pnpm --dir apps/web test` · `lint` · `typecheck` 통과
- [ ] 3구간(375·900·1280) 화면 캡처로 패널 확인
