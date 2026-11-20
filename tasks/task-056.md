# task-056 PROD-02S AI 대본 3안 선택 UI·brief 외부 전송 고지

| 항목 | 내용 |
|---|---|
| 웨이브 | W9 |
| 선행 | task-048 |
| 위험도 | 보통 |
| 보안 영향 | 노출 면 고지(brief 텍스트가 Claude로 전송) |
| 담당 | builder |
| 근거 | `docs/03_SCREENS_UX.md` 19·46행(PROD-02S), `docs/04_API.md` 47행(A-14 shopping 응답 `variants`·`facts_to_check`·notes `voice.narration_stale`), `tasks/task-048.md#구현 결정` |
| 쓰기 허용 | `apps/web/src/components/production/shopping/**`, `apps/web/src/components/production/edit/AiDraftButton.tsx`·`api.ts`, `apps/web/src/server/api/production.ts`(AiDraftResult 확장), `apps/web/src/app/api/production-jobs/[id]/ai-draft/**`, 해당 테스트 |

## 할 것
- 웹 relay·AiDraftResult가 `variants`·`facts_to_check`를 브라우저까지 전달.
- PROD-02S "AI 대본 3안 만들기": 실행 전 "브리프 텍스트가 외부 AI(Claude)로 전송됩니다" 고지, 결과 3안 카드(후킹 유형·문장 4개·글자 수·[확인 필요] 배지)·확인할 사실 목록·"이 안 사용"(대본 4문장만 교체, 저장 전 미저장 상태), `voice.narration_stale` 안내, 실패 시 "다시 시도"(직접 입력 유지).
- 반응형 3구간·토큰만·한국어 문구, AI 텍스트는 이스케이프(비신뢰).

## 하지 않을 것
- API·DB 수정, `design/`(출처 미상) 참조.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/web && pnpm lint && pnpm typecheck && pnpm test` 통과(relay가 variants 전달·3안 렌더·이 안 사용이 script만 교체·고지 문구 존재 테스트 포함)
