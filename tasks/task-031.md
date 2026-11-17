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
