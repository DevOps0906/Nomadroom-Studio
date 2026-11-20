// task-059 L5 테스트 공용: A-12 PUT 낙관적 잠금을 흉내 내는 가짜 fetch(rev_no·updated_at 문자열 비교).
// 웹은 base_updated_at을 가공 없이 보내므로 문자열이 그대로 같아야 통과한다.

export function lockServer(start: { rev_no: number; updated_at: string; approved: boolean }) {
  const s = { ...start, tick: 0 };
  const sent: string[] = [];
  const f = (async (_url: RequestInfo | URL, init?: RequestInit) => {
    const b = JSON.parse(String(init?.body)) as { base_rev_no: number; base_updated_at: string };
    sent.push(b.base_updated_at);
    if (b.base_rev_no !== s.rev_no || b.base_updated_at !== s.updated_at) {
      return new Response(JSON.stringify({ code: "CONFLICT", message: "다른 곳에서 먼저 수정되었습니다." }), { status: 409 });
    }
    if (s.approved) s.rev_no += 1;
    s.approved = false;
    s.tick += 1;
    s.updated_at = `2026-11-20T00:00:00.00000${s.tick}Z`;
    const revision = { id: `r${s.rev_no}`, rev_no: s.rev_no, validation: { errors: [], warnings: [] }, approved_at: null, updated_at: s.updated_at };
    return new Response(JSON.stringify({ revision }), { status: 200 });
  }) as typeof fetch;
  return { f, sent, state: s };
}
