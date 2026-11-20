# task-049 일본어판 파생·번역 A-20

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 |
| 선행 | task-047 |
| 위험도 | 높음 |
| 보안 영향 | 외부 계약(Claude) · 텍스트 외부 전송 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-20, `docs/05_DATA_MODEL.md`(lang·derived_from), `tasks/plan-shopping-japanese.md#팀장 설계 결정` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/translate*.py`, 테스트 |

## 할 것
- 승인된 ko 리비전 → ja 리비전 파생(컷·구도·마스크 고정 복사), Claude 구어체 번역 초안(형식별 텍스트 필드만), ko 변경 시 재파생 경고.

## 하지 않을 것
- 원본 영상·음성 전송, ja에서 컷 수정 허용.

## 완료 조건 (실행 가능한 확인)
- [ ] `pytest -q tests/production` 통과(파생 후 텍스트 외 필드 동일, 번역 모의 응답)

## 착수 결정 (팀장 2026-11-20, challenger REVISE 반영)
- J1 범위: A-20 파생·번역 + A-12 GET·PUT·A-13 승인의 `lang=ja` + 원본 변경 감지. **세 형식 모두**(variety 포함). ja 렌더는 task-050·051, 화면은 task-052.
- J2 파생 원본(사람 질문 → 팀장 기본값): **현재 ko 리비전이 승인된 경우만**(과거 승인본 불가, 400). ja 생성·편집·승인 허용 조건 = 현재 ko 승인 + ja 렌더 rendering 아님. job 상태는 바꾸지 않는다.
- J3 텍스트 경로(🔴4): 형식별 번역 대상 JSON 경로를 코드 상수로 고정하고 테스트로 고정 — category: hook 문구·`header.lines[]`·`items[].text`·`overlays[].text` / variety: `subtitles[].text`·`reactions[]` 문구·`header` 문구 / shopping: `script[]`·`cta.text`. kind·ref·style·motion·voice·disclosure 등은 번역 대상 아님. disclosure는 서버가 ja 기본값("PR")으로 넣는다. `spec.lang`은 서버가 ja로 쓴다.
- J4 검증(🔴1): 검증 함수에 job.lang 대신 **리비전 lang**을 넘긴다. variety 스키마 `lang`을 ko|ja로 확장(validation_variety.py 쓰기 허용 추가).
- J5 저장·승인 RPC(🔴2): 000016 RPC는 건드리지 않고 `20261120000027_ja_revisions.sql`에 ja 전용 저장·승인·파생 RPC 추가(current_ja_revision_id 기준, derived_from 필수, job 상태 불변, 승인본이면 새 rev_no). A-13 요청에 `lang?`(기본 ko).
- J6 음성(🔴3): 파생 시 녹음 참조(shopping `voice.narration_asset_ids`, category `hook.audio_asset_id`)는 비우고 ja 기본 TTS 설정. 승인 시 ja 리비전이 ko 원본 spec의 녹음 자산을 참조하면 오류(`ja.voice_from_ko`), TTS 목소리는 ja 계열이어야 함(기존 voice_lang 규칙 재사용).
- J7 편집 가드(🟡): A-12 PUT(ja)은 정규화된 model_dump에서 J3 경로와 음성 필드를 가린 뒤 derived_from ko spec과 깊은 비교(배열 길이 포함) — 다르면 400 `ja.locked_field`.
- J8 원본 변경(🟡): GET(ja) 때 **읽는 시점에 계산** — derived_from ≠ 현재 ko 승인 리비전이면 오류 `ja.source_changed`(승인 차단, "다시 만들기" 안내). 저장된 validation과 별개로 응답에 합친다.
- J9 번역 호출(🟡): AI 초안과 **별도 카운터·별도 멱등 키 공간·별도 60초 규칙**(작업당 3회, 가정 — Q7 값 재사용). 기록에 종류를 남긴다. Claude 입력은 J3 경로의 ko 텍스트만, 출력은 같은 경로·개수(불일치는 재시도 1회 후 502). 원문에 없는 숫자 토큰(NFKC)이 생기면 위반.
- J10 ja 내용 규칙(🟡): 승인 차단 = `[확인 필요]`·`[確認必要]` 잔존, 금지 품목. 경고 = ja 금지 문구 상수(가정 목록). ja 글자 수 규칙은 두지 않는다(가정, 기록).
- 쓰기 허용 확장: 000027 + pgTAP, `apps/api/app/production/validation_variety.py`(lang만)·`spec.py`·`validation_shopping.py`(lang 전달·ja 규칙), `apps/api/app/routes/production_ai.py`(A-20 라우트 둘 경우), `docs/04_API.md` A-12·A-13·A-20 행, `docs/05_DATA_MODEL.md` 해당 행, ERD·웹 타입 재생성.

## 구현 결정 (builder 2026-11-20)
- RPC(000027): `reserve_translation`·`create_ja_translation`·`fail_translation`(A-20), `save_ja_revision`(A-12 ja), `approve_ja_revision`(A-13 ja), 공통 조건 `_ja_writable(job, ko)`. NR012 = 입력 리비전이 현재 승인 ko 아님 → 400.
- 카운터: `production_jobs.translate_count`·`translate_requests`(원소 `kind:"translate"`). 상한은 설정 `ai_draft_max_per_job` 값(3) 재사용, 카운터는 별도.
- ja 리비전 `origin`은 기존 check 안의 `ai_draft`(번역 초안)·`user`(사람 수정). 새 origin 값은 두지 않음.
- 기본 TTS(가정): `ja-JP-NanamiNeural`, rate는 ko tts rate를 잇고 없으면 category `+50%`·shopping `+0%`.
- ja 금지 문구 경고(가정): `絶対おすすめ`·`神アイテム`·`今すぐ`(validation_shopping.JA_BANNED_PHRASES). ja 글자 수 규칙 없음.
- 쇼핑 ja의 `[확인 필요]`·`[確認必要]`는 validation_shopping(`script.unverified`)이, category·variety는 `ja.unverified`가 막는다. 금지 품목은 세 형식 모두 `ja.banned_category`.
- 빈(공백) ko 문구는 Claude에 보내지 않고 그대로 둔다. 숫자 토큰은 NFKC 뒤 `\d+([.,]\d+)*`(쉼표 제거)를 경로별로 비교.
- A-09 상세 `current_revision.ja.validation`에는 `ja.source_changed`를 합치지 않는다(A-12 GET만, J8 범위).
- 리뷰 반영(1) 숫자 가드 확장: 한자 숫자+단위(`KANJI_UNITS`)는 값으로 바꿔 ko 숫자와 비교(半=0.5), 가격·효능어(`CLAIM_TERMS`: 半額·返金·無料·最安·割引·効果·治る·保証 등)는 ko 원문에 대응 표현이 없으면 위반(재시도 후 502). "十分"(충분히)·"一回" 같은 일반어도 잡히는 과검출 가능(재시도로 흡수, 가정).
- 리뷰 반영(2) Anthropic 키 미설정이어도 같은 Idempotency-Key의 done 기록은 200 replay(failed는 502), 새 요청·처리 중은 503. 예약 RPC를 부르지 않는다(작업 행 기록을 읽음).
- 리뷰 반영(3) `reserve_translation`은 `pg_advisory_xact_lock(hashtextextended('reserve_translation:'||workspace||':'||key))`로 작업 간 같은 키 동시 예약을 직렬화. ja 저장 낙관적 잠금은 ko(000016)와 같은 계약으로 두고 추가하지 않음.
- 과검출 방지: 한자 숫자 판정 전에 관용어(`KANJI_IDIOMS`: 十分·一回·一度·一番·一緒·一人·一つ·一気·一部·一応·一生·半分·一瞬·一日中, 가정 목록)를 지운다. 一本처럼 수량일 수 있는 말은 넣지 않음.
