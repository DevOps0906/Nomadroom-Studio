import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const { SESSION_EXPIRED_PATH } = await import("@/server/api/client");
const { EVIDENCE_SESSION_EXPIRED_PATH, REASON_LABELS, fetchEvidence, pickEvidence, reasonLabel } = await import("./evidence");
const { EvidenceView } = await import("./evidence-view");
const { EvidenceButton } = await import("./evidence-dialog");
type Evidence = import("./evidence").Evidence;
type EvidenceState = import("./evidence-view").EvidenceState;

const ID = "00000000-0000-4000-8000-0000000000e1";
const NOW = Date.parse("2026-11-17T00:00:00Z");
const noop = () => {};

function ev(over: Partial<Evidence> = {}, status: Evidence["candidate"]["status"] = "producible"): Evidence {
  return {
    candidate: { id: ID, title: "후보 <b>제목</b>", status },
    prev: { observed_at: "2026-11-15T00:00:00Z", view_count: 1000 },
    curr: { observed_at: "2026-11-16T00:00:00Z", view_count: 1010 },
    growth_pct: 1,
    reason: null,
    needs_prev: false,
    next_observation_at: "2026-11-18T00:00:00Z",
    ...over,
  };
}

const render = (state: EvidenceState, opsUrl = "https://ops.example.com/") =>
  renderToStaticMarkup(<EvidenceView state={state} fallbackTitle="목록 제목" titleId="t" opsUrl={opsUrl} onRetry={noop} onClose={noop} />);
const ok = (data: Evidence) => render({ kind: "ok", data, now: NOW });
const rows = (html: string) => (html.match(/<tr data-row=/g) ?? []).length;

describe("reason 코드 문구", () => {
  it("PRD#9 10종 전부 한국어 문구", () => {
    const codes = ["market", "category", "format", "views_min", "not_cc", "broadcaster", "keyword", "no_prev", "license_unknown", "growth_out_of_range"];
    expect(Object.keys(REASON_LABELS).sort()).toEqual([...codes].sort());
    for (const c of codes) expect(reasonLabel(c)).toMatch(/[가-힣]/);
  });

  it.each(["unknown", "", null, 1, "toString", "__proto__"])("10종 밖은 null: %s", (v) => {
    expect(reasonLabel(v)).toBeNull();
  });
});

describe("pickEvidence", () => {
  it("10종 밖 reason → null, 여분 필드 제거", () => {
    const e = pickEvidence({ ...ev(), reason: "secret_rule", extra: 1, candidate: { id: ID, title: "t", status: "pending", x: 1 } });
    expect(e?.reason).toBeNull();
    expect(e).not.toHaveProperty("extra");
    expect(e?.candidate).not.toHaveProperty("x");
  });

  it("형식이 틀리면 null", () => {
    expect(pickEvidence({ ...ev(), candidate: { id: ID, title: "t", status: "weird" } })).toBeNull();
    expect(pickEvidence(null)).toBeNull();
  });
});

describe("fetchEvidence", () => {
  const signal = new AbortController().signal;
  const res = (status: number, body: unknown = {}) => (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;

  it("상태코드 → 결과", async () => {
    expect((await fetchEvidence(ID, signal, res(401))).kind).toBe("unauthorized");
    expect((await fetchEvidence(ID, signal, res(404))).kind).toBe("not_found");
    expect((await fetchEvidence(ID, signal, res(502))).kind).toBe("error");
    expect((await fetchEvidence(ID, signal, res(200, { evidence: ev() }))).kind).toBe("ok");
    expect((await fetchEvidence(ID, signal, res(200, { evidence: {} }))).kind).toBe("error");
  });

  it("세션 정리 경로는 서버 상수와 같다", () => {
    expect(EVIDENCE_SESSION_EXPIRED_PATH).toBe(SESSION_EXPIRED_PATH);
  });
});

describe("EvidenceView", () => {
  it("로딩: 스켈레톤 + 목록 제목", () => {
    const html = render({ kind: "loading" });
    expect(html).toContain('data-state="loading"');
    expect(html).toContain('role="status"');
    expect(html.match(/<div role="status"[^>]*>/)?.[0]).not.toContain("aria-label");
    expect(html).toContain("목록 제목");
  });

  it("제작 가능: 표 2행 + 증가율 + reason null 폴백 + 영상 만들기, 제목 이스케이프", () => {
    const html = ok(ev());
    expect(rows(html)).toBe(2);
    expect(html).toContain("날짜(KST)");
    expect(html).toContain("+1.0%");
    expect(html).toContain("허용 증가율 안");
    expect(html).toContain('href="https://ops.example.com/"');
    expect(html).toContain("후보 &lt;b&gt;제목&lt;/b&gt;");
    expect(html).not.toContain("<b>제목</b>");
  });

  it("조건 제외: 사유가 증가율보다 먼저, 영상 만들기 없음", () => {
    const html = ok(ev({ reason: "growth_out_of_range", growth_pct: 12.5 }, "excluded"));
    expect(html.indexOf("허용 증가율 범위 밖")).toBeGreaterThan(-1);
    expect(html.indexOf("허용 증가율 범위 밖")).toBeLessThan(html.indexOf("+12.5%"));
    expect(html).not.toContain("영상 만들기");
  });

  it("조건 제외 reason null: 사유 줄 생략", () => {
    const html = ok(ev({ reason: null }, "excluded"));
    expect(html).not.toContain("data-reason");
  });

  it("근거 대기(license_unknown, 두 시점): 표 + 증가율 + 사유", () => {
    const html = ok(ev({ reason: "license_unknown" }, "pending"));
    expect(rows(html)).toBe(2);
    expect(html).toContain("라이선스 미확인");
    expect(html.indexOf("+1.0%")).toBeLessThan(html.indexOf("라이선스 미확인"));
  });

  it("이전 관측값 필요: 현재 1행 + 다음 관측 시각", () => {
    const html = ok(ev({ prev: null, needs_prev: true, reason: "no_prev", growth_pct: null }, "pending"));
    expect(html).toContain("이전 관측값 필요");
    expect(rows(html)).toBe(1);
    expect(html).toContain('data-row="현재"');
    expect(html).toContain('dateTime="2026-11-18T00:00:00Z"');
  });

  it("관측 없음(curr null): 안내 + 다음 관측, 표 없음", () => {
    const html = ok(ev({ prev: null, curr: null, needs_prev: true, growth_pct: null }, "pending"));
    expect(html).toContain("아직 관측 기록이 없습니다");
    expect(rows(html)).toBe(0);
  });

  it("이전 관측값 필요 + license_unknown: 사유 줄 표시", () => {
    const html = ok(ev({ prev: null, needs_prev: true, reason: "license_unknown", growth_pct: null }, "pending"));
    expect(html).toContain("이전 관측값 필요");
    expect(html).toContain("라이선스 미확인");
    expect(html.indexOf("이전 관측값 필요")).toBeLessThan(html.indexOf("라이선스 미확인"));
  });

  it("관측 없음 + market(제외): 사유가 맨 위", () => {
    const html = ok(ev({ prev: null, curr: null, needs_prev: true, reason: "market", growth_pct: null }, "excluded"));
    expect(html).toContain("시장 불일치");
    expect(html.indexOf("시장 불일치")).toBeLessThan(html.indexOf("아직 관측 기록이 없습니다"));
  });

  it("다음 관측 시각이 지났으면 관측 가능 문구", () => {
    const html = ok(ev({ prev: null, needs_prev: true, next_observation_at: "2026-11-16T00:00:00Z" }, "pending"));
    expect(html).toContain("관측 가능(기록 검증 실행 시 반영)");
  });

  it("실패: 다시 시도, 재시도 중 잠금", () => {
    const html = render({ kind: "error", retrying: false });
    expect(html).toContain('role="alert"');
    expect(html).toContain("다시 시도");
    const busy = render({ kind: "error", retrying: true });
    expect(busy.match(/<button[^>]*aria-busy="true"[^>]*>/)?.[0]).toContain('disabled=""');
  });

  it("404: 목록으로 돌아가기", () => {
    const html = render({ kind: "not_found" });
    expect(html).toContain('data-state="not_found"');
    expect(html).toContain("목록으로 돌아가기");
    expect(html).not.toContain("영상 만들기");
  });
});

describe("EvidenceButton", () => {
  it("활성 버튼, 처음엔 다이얼로그 없음", () => {
    const html = renderToStaticMarkup(<EvidenceButton candidateId={ID} title="t" opsUrl="" />);
    const btn = html.match(/<button[^>]*>관측 근거<\/button>/)?.[0] ?? "";
    expect(btn).toContain('aria-haspopup="dialog"');
    expect(btn).not.toContain("aria-disabled");
    expect(html).not.toContain("<dialog");
  });
});
