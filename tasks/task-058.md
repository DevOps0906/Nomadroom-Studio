# task-058 쇼핑 녹음 상한 ko·ja 공용 8개

| 항목 | 내용 |
|---|---|
| 웨이브 | W10 후속(task-053 인수 결함) |
| 선행 | task-049 |
| 위험도 | 높음(마이그레이션) |
| 보안 영향 | 없음(상한 숫자만) |
| 담당 | builder |
| 근거 | task-053 API 인수 보고: ko 녹음 4개가 있으면 ja 녹음 업로드 409(`shopping.MAX_NARRATIONS`=4 작업 전체, DB 트리거 000023 같은 상한) |
| 쓰기 허용 | `apps/api/app/production/shopping.py`(MAX_NARRATIONS), `supabase/migrations/20261120000029_narration_limit.sql`, 해당 pgTAP·API 테스트, `docs/04_API.md` A-10 행, `docs/05_DATA_MODEL.md` 해당 행 |

## 결정 (팀장)
- 자산에 lang이 없으므로 언어별 상한 대신 작업 전체 상한을 8(ko 4 + ja 4, 가정)로 올린다. 문장별 4개 규칙(리비전당)은 spec 검증이 그대로 지킨다.
- 트리거 함수는 000023 본문을 복사해 narration 상한 숫자만 바꾼다(다른 kind 상한 불변).
- challenger 생략(상수 하나 변경, 팀장 판단) — 변경 후 codex-reviewer(code)+reviewer(contract).

## 완료 조건
- [ ] ko 녹음 4개 보유 쇼핑 작업에 ja 녹음 4개 업로드 성공, 9번째는 409(API 테스트·pgTAP)
- [ ] api pytest 전체·supabase test db 통과

## 구현 결정
- `20261120000029_narration_limit.sql`: 000023 `production_assets_source_limit()` 본문을 `create or replace`로 복사, `case new.kind when 'narration' then 8 else 10`만 변경(트리거 정의·revoke 유지).
- API `shopping.MAX_NARRATIONS = 8`. 테스트는 기존 test_shopping_api.py 녹음 상한 테스트와 pgTAP production_shopping_api_test.sql 7번을 4+4 허용·9건째 거부로 고쳤다(plan 29→30).
