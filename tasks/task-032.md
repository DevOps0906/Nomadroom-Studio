# task-032 댓글·출처 오버레이 레이어

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-028 |
| 위험도 | 보통 |
| 보안 영향 | 없음(운영자 입력 문구는 이스케이프, 렌더러는 텍스트만 그림) |
| 담당 | builder |
| 근거 | `docs/05_DATA_MODEL.md#편집안-spec-필드`(overlays), `spec PROD-02`, `docs/research/category-shorts-ref/` |
| 쓰기 허용 | `apps/worker/production/overlays.py`, `apps/worker/tests/production/test_overlays.py`, `apps/api/app/production/spec.py`(overlays 검증 추가만), `apps/api/tests/production/test_spec_overlays.py`, `apps/web/src/components/production/edit/OverlaysTab.tsx` |

## 할 것
- task-021 리뷰 🟡3: overlays와 자막의 시간·위치 겹침 경고를 `spec.py`에 추가한다.
- spec `overlays`(댓글 카드: 문구·표시 구간·위치, 출처 표기) 검증·렌더 합성. PROD-02 댓글·출처 탭에서 직접 입력(D-C6).
- 구간이 영상 길이를 벗어나거나 겹침이면 오류로 표시.

## 하지 않을 것
- 운영 사이트 연동, 이미지·외부 URL 첨부, 기존 spec 필드 의미 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_spec_overlays.py` · `cd apps/worker && pytest -q tests/production/test_overlays.py` 통과
- [ ] 오버레이 포함 샘플 렌더 `ffprobe` 가 608×1080·30fps 유지
- [ ] `pnpm typecheck && pnpm test` 통과

## 구현 결정
- 위치 x·y = 608×1080 화면에서 카드 중심(px). 범위 밖은 오류 `overlays.pos`. 문구는 한 줄·60자 이하(`overlays.text.newline`·`overlays.text.long`).
- 같은 종류(comment·source) 구간 겹침은 오류 `overlays.overlap`(경로는 뒤 행). 다른 종류는 동시 표시 가능.
- 자막 겹침 경고 `overlays.caption_overlap`(task-021 🟡3): 시간이 겹치고 |오버레이 y − 자막 y| < 75(자막 기본 y: emph 390, 그 외 700)이면 경고. 렌더는 막지 않음.
- 렌더: 워커 `overlays.py`가 PIL로 카드(댓글=밝은 카드, 출처=반투명 어두운 띠)를 그려 자막 위에 합성. 필터 문자열에 사용자 텍스트 없음. 폭 초과는 12pt까지 축소 후 `text_too_long`. 어댑터가 형식·범위·겹침 오류를 `render_failed`로 거부(기존 "오버레이 있으면 실패" 제거).
- 웹: `OverlaysTab`(댓글·출처 탭), Draft에 `overlays` 추가(빈 목록이면 spec에 키 생략). ref는 보존만 하고 입력 칸 없음.
- 호환: 기존 자산·spec 필드 의미 변경 없음. 이미지·URL 첨부 미지원.
