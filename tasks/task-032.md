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
