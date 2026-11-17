# task-024 로컬 제작 워커 prepare·render

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-023 |
| 위험도 | 높음 |
| 보안 영향 | 새 의존성(ffmpeg 호출·렌더 라이브러리) · 키·권한(워커 토큰, DB·Supabase 키 없음) · 경로 보안 · 폰트 라이선스(OFL) |
| 담당 | builder + tester |
| 근거 | `docs/adr/0003-production-render-worker.md`, `docs/adr/0001-worker-location.md`, `docs/02b_PRODUCTION_FLOW.md`, `docs/research/category-shorts-ref/`, `docs/05_DATA_MODEL.md#편집안-spec-필드`(매핑) |
| 쓰기 허용 | `apps/worker/production/**`, `apps/worker/pyproject.toml`·`apps/worker/main.py`(워커 골격 신규 — task-009 보류로 아직 없음), `apps/worker/tests/production/**`, `apps/worker/fonts/**`·`apps/worker/licenses/**`(폰트 3종·라이선스 보존), `.env.example`(이름만) |

## 할 것
- `prepare`: W-05 수령 → W-06 서명 GET → 구간 추출·analysis·시트 → W-07 서명 PUT → W-09. `render`: 첨부 음성·합성·608×1080·30fps·H.264/AAC·리포트·프리셋 버전 기록.
- 배포본 렌더러 이식 + 어댑터(spec→project 매핑). 작업 폴더 안에서만 파일명 결정, 절대 경로·`..` 거부.
- 워커 골격 최소 생성: uv 프로젝트, 워커 토큰·API 주소 환경변수, W-05 폴링 루프·작업 종류 분기(prepare/render). task-009 재개 때 수집 작업 종류를 같은 실행 파일에 추가한다(D-C2·팀장 결정).
- ffmpeg는 설정한 경로(시스템 ffmpeg)를 쓴다. imageio-ffmpeg 동봉 바이너리는 라이선스 확인 전까지 쓰지 않는다.
- 단계별 W-08 진행 보고, 만료 시 URL 재발급, `hook_too_long`·`text_too_long` 실패 보고.

## 하지 않을 것
- DB·Supabase 직접 접속, 로컬 포트 개방, TTS(030)·URL 다운로드(031)·오버레이(032), 무음·가짜 음성 대체, 토큰·서명 URL 로그 출력.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/worker && pytest -q tests/production` 통과(경로 보안·폴더 이탈 거부·hook_too_long·만료 URL 재발급, API는 목)
- [ ] 샘플 구간 렌더 산출물 `ffprobe -v error -show_streams` 가 608×1080·30fps·h264/aac
- [ ] `~/.claude/nomad/bin/secscan license` GPL·AGPL 0건(폰트·의존성) · 코드에 `supabase`·DB 접속 문자열 0건(`grep -ri supabase apps/worker/production`)
