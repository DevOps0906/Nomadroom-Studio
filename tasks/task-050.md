# task-050 일본어 TTS·렌더

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-049, task-030 |
| 위험도 | 높음 |
| 보안 영향 | 새 자산(JP 글꼴 OFL) · TTS 의존 |
| 담당 | builder + tester |
| 근거 | `docs/research/category-shorts-zip-analysis.md#3`(일본어 규격), `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/worker/production/**`(lang 분기), `apps/worker/production/fonts/**`, 테스트 |

## 할 것
- 카테고리형 ja 훅 TTS·쇼핑 ja 내레이션, Noto Sans CJK JP, ja 표기 "PR", (작업, 리비전, ja) 별도 MP4.

## 하지 않을 것
- 무음 대체, 라이선스 미확인 글꼴.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/worker && pytest -q tests/production` 통과(ja 렌더 2형식)

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- K1 범위: category·shopping ja 렌더 종단. variety+ja는 A-15 RPC 전 409(task-051 전까지). 화면은 task-052.
- K2 요청 RPC(🔴2): 새 `20261120000028_ja_render.sql`에서 `request_render_run`을 000017 본문 기준으로 교체해 ja 분기 추가 — job 잠금 안에서 리비전 = `current_ja_revision_id`·승인됨, `derived_from` = 현재 ko 리비전이고 그 ko가 승인됨(TOCTOU 방지), job 상태 **inspect·done**(문서 기존 조건 유지, 사람 질문의 팀장 기본값), job 상태는 바꾸지 않음. ko 분기는 그대로.
- K3 재시도(🔴1): ja는 A-16 재시도 없음(409 "ja는 다시 렌더 요청") — 실패 run은 A-15 재요청으로(NR014 미해당). 문서 A-16에 명시.
- K4 훅 음성(🔴3): W-06은 언어와 무관한 최신 hook_audio 대신 **렌더 리비전 spec의 `hook.audio_asset_id`가 가리키는 자산만** 준다(ko·ja 공통, 이 작업 소유·ready 확인). spec이 tts면 TTS, 워커 TTS 꺼짐이면 `tts_failed`(녹음·무음 대체 없음, W-09 정본).
- K5 글꼴(🔴4·🟡): `apps/worker/fonts/NotoSansCJKjp-Bold.otf`(+ 제목용 JP 굵은 글꼴 — 같은 패밀리 Black이 있으면 Black) 공식 notofonts/noto-cjk 릴리스 **태그 고정**·SHA-256 기록, 라이선스는 기존 `NotoSansCJK-OFL.txt` 재사용, `apps/worker/licenses/THIRD_PARTY.md` 갱신("JP는 P0 제외" 정정), `secscan license` 확인. lang=ja면 제목·자막·오버레이·CTA 모두 JP 글꼴, 카테고리 ja 제목 둘째 줄은 흰색(규격 `category-shorts-zip-analysis.md#3`). `pick_font`에 lang 인자.
- K6 줄바꿈(🔴5): 쇼핑(및 공용 텍스트) ja는 글자 단위 줄바꿈 + 행두 금칙(、。」』）！？ー・ぁぃぅぇぉっゃゅょ 등)·행말 금칙(「『（ 등).
- K7 하드코딩 정리: `render.py:35`(ko만), `overlays.py:15`, `runner.py` 결과 파일명(`result_{lang}.mp4`)·report fonts를 lang 기준으로. report에 사용 글꼴 기록, 테스트가 JP 글꼴 사용을 단언.
- K8 배포(🟡): W-05 capabilities에 `ja` 추가, claim은 `ja`를 알린 워커에게만 ja run을 준다(000028). 배포 순서 문서화(워커 먼저).
- K9 쓰기 허용 정정: `apps/worker/production/**`·`apps/worker/fonts/**`·`apps/worker/licenses/THIRD_PARTY.md`·`apps/api/app/routes/production_render.py`·`worker_production.py`(W-05·W-06)·000028·pgTAP·`docs/04_API.md`(A-15·A-16·W-05·W-06)·테스트. 완료 조건에 pgTAP·API 테스트(ja 요청·완료·실패·만료 후 job 상태 불변, source_changed 거부, variety ja 409, A-16 ja 409, capability 없는 워커 미배정) 추가.

## 구현 결정 (builder 2026-11-20)
- DB(000028): `request_render_run` ja 분기(job inspect·done, 리비전 = `current_ja_revision_id`·승인, `derived_from` = 현재 승인 ko 아니면 NR010 "원본(ko) 편집안이 바뀌었습니다…", job 상태 불변), `retry_render_run` ja run → NR010, `claim_production_task(…, formats)` ja run은 `'ja'` 알린 워커만(복구 무조건). W-09·만료는 000017·000023이 이미 ko만 job 전이라 변경 없음.
- API: variety+ja는 작업 조회 후 RPC 전 409 field `lang`. W-05 `capabilities` 허용값 `shopping`·`ja`. W-06 category render의 hook_audio는 run 리비전 spec `hook.audio_asset_id`가 가리키는 이 작업·ready·`render_run_id` null 자산만(ko 포함, 최신 녹음 대체 없음).
- 글꼴: notofonts/noto-cjk 태그 `Sans2.004`의 `NotoSansCJKjp-Bold.otf`·`NotoSansCJKjp-Black.otf`(같은 태그 KR 파일 SHA가 기존 KR과 일치, 태그 루트 LICENSE = 기존 OFL 파일). `production/fonts.py`에 언어별 경로. category ja = 제목 Black·자막/오버레이 Bold·둘째 줄 흰색, shopping ja = 전부 Bold(`pick_font(text, lang)`, ja는 JP만).
- 줄바꿈(가정): ja 금칙 목록은 `shopping/text.py` `NO_START`·`NO_END`(追い出し 방식). category 자막·오버레이는 기존대로 한 줄 자동 축소.
- 결과 파일명 `result_{lang}.mp4`, report에 `lang`·`fonts`(category는 렌더러가 실제 글꼴 기록). 워커 `CAPABILITIES = ["shopping", "ja"]`.
- 발견·수정: 쇼핑 알약 레이어가 여러 줄 bbox(실수)를 그대로 `Image.new` 크기로 써 TypeError — 정수 올림(ko 여러 줄에도 잠재).
- 배포 순서: ja 지원 워커 먼저 → 000028·API(04_API W-05에 기록).
