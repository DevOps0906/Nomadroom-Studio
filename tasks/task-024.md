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

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 사용자 결정(2026-11-19): 배포본(`카테고리형 영상제작_배포용 .zip`의 `category-shorts/`) 코드·폰트를 저장소에 복사·수정해 쓸 권리 있음. 출처를 `apps/worker/licenses/THIRD_PARTY.md`에 기록한다.
- 이식 원본: 팀장이 scratchpad에 압축을 푼 `zip-category/category-shorts/`(scripts/common·prepare·render·tts.py, assets/fonts, licenses, checksums.json). 폰트는 checksums.json 해시와 대조한 뒤 복사.
- 쓰기 허용 추가: `apps/worker/uv.lock` · `docs/adr/0001-worker-location.md`·`0003-production-render-worker.md`(워커 위치 `apps/worker`로 정정만).
- F1 폰트: P0는 Pretendard-Black·NotoSansCJKkr-Bold + OFL 2종만(일본어 jp 폰트 제외, task-050에서).
- F2 진행 보고: 단계 전환과 별도로 60초마다 백그라운드 W-08. 409 받으면 즉시 중단·ffmpeg 서브프로세스 kill.
- F3 ffmpeg 입력 보안: 서명 URL을 `-i`에 넘기지 않고 httpx로 작업 폴더에 받은 뒤 처리. 모든 입력에 `-protocol_whitelist file` + 형식 고정/허용 목록(mov,mp4,matroska,webm,wav,mp3).
- F4 로그: httpx·httpcore 로거 WARNING, 토큰·서명 URL 로그 0건(caplog 테스트).
- F5 재시작: 다시 받은 task는 UUID 작업 폴더를 지우고 처음부터. W-09 성공 뒤 폴더 삭제. finish 409는 "이미 처리됨"으로 해석(04 W-09).
- F6 URL: 입력 만료 시 W-06 재호출(같은 자산 새 URL), 업로드 실패·만료 시 W-07 재호출로 새 asset_id, W-09엔 마지막 id만.
- F7 실패 코드: TextTooLong·HookTooLong 예외 → text_too_long·hook_too_long, 그 외 render_failed, hook_audio 없음 → audio_missing(stage=audio). 무음 정리는 `production/hook_audio.py`(tts.py 이름은 task-030용).
- F8 훅 음성 정본: W-06이 주는 최신 ready hook_audio(E10 복구 경로와 일치). report에 실제로 쓴 asset_id 기록. spec `hook.tts`(P1)인 리비전은 audio_missing.
- F9 preset_version이 워커 상수와 다르면 렌더하지 않고 render_failed.
- F10 ffprobe 검증: ffmpeg가 있을 때만 도는 pytest — lavfi testsrc+sine으로 원본·훅 생성 → 렌더 → 608×1080·30/1·h264·aac. 저작물 샘플 금지.
- F11 시스템 ffmpeg(GPL 빌드 가능)는 subprocess 호출·미배포라 수용(내부 도구), THIRD_PARTY.md에 기록.
