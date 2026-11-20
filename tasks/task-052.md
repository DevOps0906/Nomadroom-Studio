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

## 구현 결정 (builder 2026-11-20)
- 탭 상태는 `?lang=ja` 쿼리(서버 렌더, 새로고침 유지). 편집 화면 3종은 한 페이지(`production/[id]/edit`)라 ja 탭은 형식과 무관하게 `JaPanel` 하나(`components/production/lang/`)로 처리한다.
- ja 편집은 번역 경로(J3) 문구만 입력 필드로 연다: category `header.lines[]`·`hook.text`·`items[].text`·`overlays[].text` / variety `header.lines[]`·`subtitles[].text`·`reactions[].text` / shopping `script[]`·`cta.text`. 그 밖은 "잠금 필드" 안내만(서버 `ja.locked_field`가 정본). 음성은 편집 UI 없이 "일본어 TTS 기본값" 안내만 둔다(가정, 음성 편집은 후속).
- 번역 호출은 `shopping/ai-script.tsx`의 `retainKey` 재사용(불명확한 실패는 같은 키, 확정 응답은 새 키). 전송 고지 "ko 문구(대본·자막·제목·CTA)가 외부 AI(Claude)로 전송됩니다".
- `ja.source_changed`(A-12 GET 응답 errors)면 "다시 만들기"(A-20 재호출, 기존 ja는 보관)와 안내, 승인 차단. 번역 중 입력·버튼 비활성, 실패는 "다시 시도".
- 중계: `revision` PUT·`approve`에 body `lang`(ko 기본), `render-runs`는 lang ko·ja 허용(variety ja는 API 409 문구를 그대로 안내, 화면에서 "준비 중"으로 막지 않음), 신규 `translate`(A-20)·`report-warnings`(리포트 JSON에서 warnings만 추려 전달, 서버에서 서명 URL로 읽음).
- PROD-03 ja 탭: ja 리비전 상태·렌더 요청(A-15 lang=ja)·쇼핑 게시 문구(A-21 lang=ja)·리포트 경고. 검수 리포트 카드(ko·ja)에 `dub_overflow`(대사 번호·초과 초)·`dub_none` 표시(task-051 D7).
- 한계(가정, API 변경 금지라 못 고침): A-09 상세의 `latest_run`·`assets`에 `lang`이 없어 ja 진행률·MP4 재생·언어별 리포트 구분을 못 한다. 리포트 JSON의 `lang`·warnings 항목 필드명(`line`·`overflow_sec`)은 task-051 구현 전이라 추정이며 `lang`이 있으면 탭과 다를 때 숨긴다.
