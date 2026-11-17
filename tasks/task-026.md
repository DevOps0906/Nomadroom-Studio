# task-026 PROD-02 편집안 화면

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-022, task-025 |
| 위험도 | 보통 |
| 보안 영향 | 없음(훅 음성 업로드는 서명 URL, 문구는 이스케이프) |
| 담당 | builder |
| 근거 | `spec PROD-02`, `docs/03_SCREENS_UX.md`, `docs/04_API.md#A-10`·`#A-12`·`#A-13`, `docs/05_DATA_MODEL.md#편집안-spec-필드` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/production/[id]/edit/**`, `apps/web/src/components/production/edit/**`, `apps/web/src/app/api/production-jobs/[id]/revision/**` |

## 할 것
- 분석 시트 패널 + 제목·훅·자막 행 리스트·구도(컷) 행 리스트·타임라인 바(겹침·공백 빨강, 1.4초 미만 노랑 배지)·훅 음성 업로드·카운터.
- "저장"(오류 허용, 서버 `validation` 표시)·"승인"(오류 0일 때, 성공 시 PROD-03 이동). `base_rev_no` 충돌 안내. ~767 탭 4개·하단 고정 버튼·취소 시 미저장 확인.

## 하지 않을 것
- 댓글·출처 탭 내용(032), AI 초안 버튼(029), 클라이언트 검증을 정본으로 삼기(서버가 정본), "검증" 별도 버튼.

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(검증 오류·경고 표시, 승인 비활성 사유, 409 충돌 안내)
- [ ] hex·px 직접 사용 0건(`grep -rnE "#[0-9a-fA-F]{6}|[0-9]px" apps/web/src/components/production/edit`)
