# task-046 화면: 유형 선택·PROD-01S·PROD-02S·게시 문구

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-044 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | builder |
| 근거 | spec `PROD-00`·`PROD-01S`·`PROD-02S`·`PROD-03`(`design/spec.json`), `docs/03_SCREENS_UX.md` |
| 쓰기 허용 | `apps/web/src/app/(app)/production/**`, `apps/web/src/components/production/**`, 해당 테스트 |

## 할 것
- "내부 제작" → 유형 → 형식/분야. PROD-01S 원본 다건·권리·brief·제휴 링크·경고. PROD-02S 4문장(카운터)·문장별 컷·마스크·음성·CTA·표기. PROD-03 게시 문구 복사·권리 목록. 반응형 3구간.

## 하지 않을 것
- 일반쇼츠 화면 동작 변경, API 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `corepack pnpm --dir apps/web test`·`lint`·`typecheck` 통과
- [ ] 3구간 캡처 확인

## 구현 결정 (2026-11-20, builder)
- 라우트는 문서의 `(app)`이 아니라 실제 `(dashboard)/production/**`. 유형 선택은 모달 대신 `/production/new`의 첫 단계 화면(`type-chooser.tsx`, 고르기 전 "계속" 비활성)으로 두고, 쿼리(`kind`·`format`·`candidate_id`)가 있으면 기존 PROD-01로 바로 간다(MON-01 후보 흐름 유지).
- 쇼핑 작업은 같은 URL(`/source`·`/edit`·`/`)에서 `job.kind`·`format`으로 분기한다. 일반·예능형 컴포넌트는 손대지 않았다(타입 좁히기만).
- 쇼핑 생성은 `rights_confirmed:false`·`source_start_sec:0`·`segment_len_sec:30`을 보낸다(권리는 자산마다, 구간은 쇼핑 렌더에 쓰이지 않는다고 가정). 금지 품목 확인(`not_banned_confirmed`)은 생성 때만 보낸다.
- 원본 행은 파일 확장자로 영상(`source_upload`)·사진(`image`)을 나눈다. 사진 권리 근거는 own·licensed만 화면에서 허용(task-045 팀장 결정), 영상·BGM·녹음은 다섯 가지. 권리는 업로드 요청에 담고, 바꾸려면 삭제 후 새로 올린다.
- 업로드는 "원본 준비 시작"에서 순서대로(성공한 행은 목록에서 빠지고 실패 행에 "다시 시도"). 저장은 작업 필드(PATCH)만 보낸다.
- 편집안: `voice.narration_asset_ids` 4개(문장 순서)·`disclosure.text` 고정 "제휴 링크 포함"(ko)·사진 컷에만 `motion`(기본 zoom). 컷 원본 선택지는 사용자 `source_upload`·`image`(파생 `source`는 계보 정보가 응답에 없어 제외). AI 대본 3안·AI 생성 컷·ja 탭 실동작은 범위 밖(P1, 후속).
- A-21은 응답에 제휴 링크가 있어 브라우저→핸들러를 POST(`/publish-text`, 첫 줄 assertSameOrigin)로 중계한다(주소·캐시·로그에 남기지 않음). 자산 삭제는 DELETE `/assets/{assetId}`.
- 확인 필요(API 응답 한계): ① (갱신) task-045가 A-09 상세 `assets[]`에 `rights`·`parent_asset_id`를 넣는다. PROD-03 권리 목록은 값이 오면 채우고, 비어 있으면 "권리 정보가 입력되지 않았습니다"를 보인다. ② 준비 시작 트리거가 ready `source_upload` ≥1을 요구해 사진만으로는 준비를 못 시작할 수 있다(화면은 경고만, 서버가 409).
- 3구간 캡처: 로그인 세션·API 없이 실행하지 못해 미검증(`renderToStaticMarkup` 테스트로 구조만 확인).

- 리뷰 반영: 쇼핑 판별은 `job.kind === "shopping"` 하나(목록·편집 페이지 포함). 새 작업에서 업로드 성공 뒤 준비 시작이 실패해도 재시도에서 원본 수에 올린 자산을 더한다(`countSources`). 표기 문구는 `rest.lang`(ko "제휴 링크 포함"·ja "PR")으로 고른다. 목록 "내부 제작" 버튼 문구는 03_SCREENS_UX PROD-00과 같다.
