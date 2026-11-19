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

## 구현 결정 (2026-11-19, builder)
- U1 download_ranges 미사용(G3·G4 충돌): yt-dlp 2026.10.26은 구간 다운로드를 FFmpegFD(ffmpeg가 URL을 직접 받음 → 연결별 IP 검사 우회)로만 하고, ffmpeg가 없으면 중단한다. G3·G2를 우선해 전체 합본 파일을 네이티브로 받고(max_filesize·받은 바이트 500MB·전체 20분·socket 30초 상한) 구간은 기존 prepare(ffmpeg file_input)가 자른다. 받기 전 `duration`으로 구간 밖이면 `range_invalid`. 팀장 확인 필요.
- U2 SSRF: `fetch_url._GuardedYDL.build_request_director`가 요청 핸들러를 전용 UrllibRH 하나로 고정(https만, 프록시·ftp·data·file 처리기 없음). HTTPSConnection의 `_create_connection`에 yt-dlp `create_connection(_create_socket_func=guard.connect)`를 꽂아 실제 접속 IP마다 `is_global`·비멀티캐스트(IPv4 매핑 포함) 검사. 리다이렉트도 새 연결이라 같은 검사. socket 전역 패치 없음. 플러그인은 `yt_dlp.globals.plugin_dirs=[]`(yt-dlp 내부 전역)로 미로드.
- U3 format: `best[height<=1080][ext=mp4|webm][protocol=https][vcodec!=none][acodec!=none]` 합본만(병합 없음 → ffmpeg 불필요). 현재 YouTube 합본은 대개 360p라 화질이 낮을 수 있다. `ffmpeg_location`은 없는 경로, `js_runtimes={}`·`remote_components=[]`(외부 JS 런타임·ejs 미사용) — 필요한 영상은 `url_unavailable`.
- U4 API: `app/production/url_guard.py`(문자열 검사만). POST·PATCH는 보낸 값+저장 값으로 최종 검사(G8), upload로 바꾸면 source_url null. A-11은 DB check(url ⇒ source_url·rights)로 보장돼 추가 검사 없음.
- U5 DB: 000019는 claim 함수만 교체. `source_url` 키는 prepare·url·rights일 때만 `||`로 붙이고 그 외 반환 모양은 000017과 같다(키를 항상 넣으면 production_render_test 14번 정확 비교가 깨짐). pgTAP `production_url_source_test.sql` 5건, db reset 후 전체 432건 통과.
- U6 웹: 원본 방식 라디오·URL 입력(권한 확인 전 비활성)·url_unavailable 안내+업로드 전환. `isYoutubeUrl`·`URL_ONLY`는 `components/production/api.ts`(폼·Route Handler 공용 1차 검사, 정본은 API). POST·PATCH Route Handler가 source_kind·source_url을 전달(assertSameOrigin 첫 줄·응답 id·status만 유지). `SaveBody`의 두 필드는 선택(없으면 upload).
- U7 `js_runtimes={}`라 YouTube 서명 해석이 필요한 영상은 `url_unavailable`이 잦을 수 있다. 그때 업로드 안내가 정상 경로다(사용자 PC에 JS 런타임 설치 안 함, 착수 결정 G6).
- 새 환경변수 없음(상한은 `fetch_url.py` 상수). 의존성 `yt-dlp==2026.10.26`(extra 없음, Unlicense, 필수 의존성 0).

## 리뷰 반영 결정 (2026-11-19, code·security 🟡 4건)
- R1 A-11: url 작업은 `rights_confirmed`와 `source_url`이 둘 다 있어야 준비 시작(아니면 400 field `rights_confirmed`, DB check와 이중 방어).
- R2 A-09 PATCH 조건부 갱신에 `source_kind=eq.<읽은 값>` 추가 — 원본 방식 동시 전환은 409.
- R3 워커 `is_public_ip`: NAT64(64:ff9b::/96)·IPv4 호환(::/96)·IPv4 매핑(::ffff:0:0/96)은 마지막 4바이트 IPv4로 재검사.
- R4 yt-dlp 실행을 별도 스레드로 돌리고 호출 스레드가 `WATCH_POLL_SEC`(0.5초)마다 취소·`MAX_RUN_SEC`(20분)를 감시. 초과·취소면 guard.abort로 이후 훅·연결에서 예외, 열린 소켓은 닫아 막힌 읽기를 깨우고 `JOIN_GRACE_SEC`(5초) 기다린 뒤 `download_failed`(시간)·중단(취소)으로 끝낸다.
- R5 위 U7(js_runtimes 미사용 → url_unavailable 시 업로드 안내).
