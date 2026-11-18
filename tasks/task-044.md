# task-044 쇼핑 API

| 항목 | 내용 |
|---|---|
| 웨이브 | W8 |
| 선행 | task-043 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(다건 업로드·제휴 링크 입력) · 입력 검증 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md` A-09·A-10·A-11·쇼핑 항목, `docs/02b_PRODUCTION_FLOW.md` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/**`, `apps/api/tests/production/**` |

## 할 것
- A-09 kind·vertical·brief·affiliates, 의약품·건기식 400. 원본 다건 업로드·자산별 권리 입력, 원본별 prepare(전부 끝나야 review). 제휴 링크 http(s)만·길이 상한. 업로드 kind `image`·`bgm`·`narration`(권리 basis 필수). **A-21 게시 문구**(쇼핑만), A-09 목록 kind·vertical·langs[]·상세 언어별 current_revision.

## 하지 않을 것
- 렌더러·화면·AI, 제휴 링크 자동 발급·외부 호출.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` 통과(금지 품목 400, 다건 prepare 상태, 권리 없는 승인 400)
- [ ] 로그에 제휴 링크·서명 URL 토큰 0건
