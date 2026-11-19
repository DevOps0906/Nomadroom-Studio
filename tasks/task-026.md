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

## 구현 결정
- 서버 검증이 정본: 저장은 오류가 있어도 허용하고 `validation`을 표시, 400(스키마·path.forbidden)은 저장 안 됨으로 표시. 승인은 상태 review·미승인·미저장 변경 없음·오류 0일 때만 활성이고 사유를 화면에 나열(오류는 `#edit-issues` 링크).
- `ApiError`에 400 응답의 `errors[]`·`warnings[]`를 보존(형식 틀린 항목은 버림). Route Handler는 `revision/_revision.ts`가 400에만 목록을 전달하고 PUT 성공 응답에서 spec은 돌려주지 않는다.
- 409(`base_rev_no` 충돌·상태 불가)는 충돌 안내 + "최신 편집안 불러오기"(새로고침)로 처리하고 저장·승인을 잠근다.
- 훅 음성: `revision/hook-audio`가 A-10 `hook_audio` 서명을 발급(50MB 가정), 완료는 기존 `uploads/{assetId}/complete` 재사용. 올리면 `audio_asset_id` 지정·`tts` 제거(저장해야 반영). 브라우저 메타 길이는 올린 직후에만 알 수 있어 카운터 경고만(승인 비차단).
- 분석 시트: 이미지 미리보기 대신 시트 N개 "보기" 버튼이 A-18 서명 URL을 눌렀을 때만 받아 새 창으로 연다(`revision/sheet/{assetId}`). 인라인 썸네일은 이미지 도메인·CSP 정책 확정 후.
- 초안(리비전)이 없으면 빈 양식 + 안내만 보이고 저장·승인 비활성(A-12는 현재 리비전이 있어야 저장 가능). ja·댓글·출처 탭은 비활성 표시.
- ~767: 훅·자막·구도·시트 4개 구역 탭, 하단 고정 버튼. 취소는 미저장이면 confirm, 이동 위치는 PROD-03(`/production/{id}`, 후속).
- 시트 열기: 클릭 직후 빈 창을 동기로 열고 `opener`를 끊은 뒤 URL로 이동(실패 시 창 닫기). `revision/sheet/{assetId}`는 작업 상세(A-09)의 ready sheet 자산 목록에 있는 id만 열고 나머지는 404.
