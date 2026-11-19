# task-031 URL 원본 (권리 확인·yt-dlp·SSRF 방지)

| 항목 | 내용 |
|---|---|
| 웨이브 | W5 |
| 선행 | task-028 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(yt-dlp) · 노출 면(외부 URL 입력·SSRF) · 저작권(권리 확인 체크) · 로그인·쿠키 우회 금지 |
| 담당 | builder + tester |
| 근거 | `docs/01_PRD.md#8`(SSRF), `docs/04_API.md#A-09`(PATCH)·`#W-05`·`#W-06`, `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/app/production/url_guard.py`, `apps/api/app/routes/production_jobs.py`(URL 검증 연결만), `apps/api/tests/production/test_url_guard.py`, `apps/worker/production/fetch_url.py`, `apps/worker/tests/production/test_fetch_url.py`, `apps/worker/pyproject.toml`·lock(의존성 추가만), `apps/web/src/components/production/source/**`(URL 입력·체크 활성화만) |

## 할 것
- API: `rights_confirmed` true일 때만 `source_url` 허용·워커에 전달. 사설망·루프백·`file:`·비 http(s) 거부, 리다이렉트 후 주소 재검사.
- 워커: 로컬에서만 yt-dlp 다운로드(쿠키·로그인 미사용), 실패 시 업로드로 전환 안내. PROD-01 "사용 권한 확인" 체크 뒤 URL 입력.

## 하지 않을 것
- 로그인·쿠키·접근 제한 우회, API 서버에서 다운로드, 권리 확인 없는 URL 처리.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_url_guard.py` 통과(127.0.0.1·10.x·169.254.x·`file:`·리다이렉트 사설 주소 거부, 권리 미확인 400)
- [ ] `cd apps/worker && pytest -q tests/production/test_fetch_url.py` 통과(다운로더 목, 쿠키 옵션 미사용 확인)
- [ ] `~/.claude/nomad/bin/secscan license` 통과(GPL·AGPL 0건) · `pnpm typecheck && pnpm test` 통과

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용 추가: `supabase/migrations/*000019*.sql`(claim 함수 교체: rights_confirmed일 때만 source_url 반환) · `supabase/tests/*production*` · `apps/api/app/routes/worker_production.py`(TaskOut source_url만) · `apps/worker/production/api.py`(Task 필드만)·`runner.py`(_prepare url 분기만) · `docs/04_API.md`(A-09·W-05) · 웹은 `components/production/source-form.tsx`·`production.test.tsx`(경로 정정).
- G1 허용 범위: YouTube만(youtube.com·www·m·youtu.be, https). yt-dlp `allowed_extractors=["youtube"]`, generic 추출기 금지. 그 외 URL은 API 400.
- G2 SSRF: API는 네트워크 요청 없이 스킴·호스트 허용 목록·IP 리터럴·포트만 검사(리다이렉트 추적 금지 — API가 발사대가 되지 않게). 연결별 실제 IP 재검사는 워커 fetch_url에서 yt-dlp 요청 핸들러 수준으로(사설·루프백·링크로컬·CGNAT·멀티캐스트 거부). 프로세스 전역 socket 패치 금지.
- G3 yt-dlp 내부 ffmpeg 차단: external_downloader 금지(네이티브만), fixup never, 후처리기 0개, 합쳐진 단일 format(≤1080p, mp4/webm)만. 산출 파일은 기존 sniff + file_input 경로로만.
- G4 상한: noplaylist, is_live 거부, max_filesize=MAX_INPUT_BYTES, socket_timeout·전체 실행 시간 상한, download_ranges로 start~start+len(+여유)만. 각 테스트.
- G5 Python API(YoutubeDL) 직접 사용, 사용자 설정·플러그인 미로드, cookiefile·cookiesfrombrowser·usenetrc·username·password 부재 단언.
- G6 의존성: extra 없이 `yt-dlp`만, exe 배포본 금지, uv.lock 갱신 후 secscan에 yt-dlp 표시 확인. 외부 JS 런타임(Deno 등)·yt-dlp-ejs는 설치하지 않는다 — 필요해서 실패하면 url_unavailable로 보고하고 화면은 "업로드로 진행" 안내(사용자 PC 새 의존성 없음).
- G7 progress_hook마다 cancel.check(). G8 url 작업에서 rights_confirmed=false PATCH는 API 400. G9 실패 detail·로그에는 호스트와 오류 분류만(URL 전체 금지).
- 순서: task-030(같은 워커 pyproject·runner 수정) 커밋 뒤 착수.
