import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// task-057 AI 영상 생성(A-22) 중계 5개 경로 + 견적→확인 모달·오류 표시·검수 3항목.

const h = vi.hoisted(() => ({ calls: [] as string[], fail: null as { status: number; code: string; message: string; field?: string } | null }));
vi.mock("server-only", () => ({}));
vi.mock("@/server/supabase/client", () => ({ createServerSupabase: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { ApiError } = await import("@/server/api/client");
const RUN = {
  id: "00000000-0000-4000-8000-0000000000c1", job_id: "j", source_asset_id: "s", result_asset_id: null, cut_ref: null, prompt: "p", duration_sec: 5,
  est_cost_krw: 1200, actual_cost_krw: null, status: "quoted", error_code: null, created_at: "t", confirmed_at: null, finished_at: null, request_id: "secret-request", platform: "secret-platform",
};
const gate = <T,>(name: string, value: T) => {
  h.calls.push(name);
  if (h.fail) throw new ApiError(h.fail.status, h.fail.code, h.fail.message, h.fail.field);
  return value;
};
vi.mock("@/server/api/production", () => ({
  listGenerationRuns: async (id: string) => gate(`list:${id}`, { items: [RUN] }),
  quoteGenerationRun: async (id: string, body: unknown, key: string) => gate(`quote:${id}:${key}:${JSON.stringify(body)}`, { run: RUN, budget: { monthly_left_krw: 50000, job_left_krw: 9000 }, replay: false }),
  confirmGenerationRun: async (id: string, runId: string) => gate(`confirm:${id}:${runId}`, { run: { ...RUN, status: "running" }, budget: null, replay: false }),
  refreshGenerationRun: async (id: string, runId: string) => gate(`refresh:${id}:${runId}`, { run: { ...RUN, status: "done" }, budget: null, replay: false }),
  getProductionDownloadUrl: async (id: string, assetId: string) => gate(`url:${id}:${assetId}`, { url: "https://signed.example/x" }),
  reviewGenerationRun: async (id: string, runId: string, c: unknown) => gate(`review:${id}:${runId}:${JSON.stringify(c)}`, { run: RUN, reviewed: true, review_checks: {} }),
}));

const list = await import("@/app/api/production-jobs/[id]/generation-runs/route");
const confirmRoute = await import("@/app/api/production-jobs/[id]/generation-runs/[runId]/confirm/route");
const refreshRoute = await import("@/app/api/production-jobs/[id]/generation-runs/[runId]/refresh/route");
const reviewRoute = await import("@/app/api/production-jobs/[id]/generation-runs/[runId]/review/route");
const gen = await import("./generation");
const api = await import("./api");
const logic = await import("./generation-logic");
const { createIntentRunner } = await import("@/components/monitoring/intent-key");

const ORIGIN = "https://studio.example.com";
const ID = "00000000-0000-4000-8000-0000000000a1";
const KEY = ["gen-", "1234", "5678"].join("");
const ctx = { params: Promise.resolve({ id: ID }) };
const rctx = { params: Promise.resolve({ id: ID, runId: RUN.id }) };
const post = (body?: unknown, origin: string | null = ORIGIN, key: string | null = null) => {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (origin !== null) headers.origin = origin;
  if (key !== null) headers["idempotency-key"] = key;
  return new Request(`${ORIGIN}/api/x`, { method: "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) });
};
const QUOTE = { source_asset_id: "00000000-0000-4000-8000-0000000000b2", prompt: " 천천히 줌인 ", duration_sec: 5 };

describe("A-22 중계 5개 경로", () => {
  beforeEach(() => {
    vi.stubEnv("APP_ORIGIN", ORIGIN);
    h.calls = [];
    h.fail = null;
  });

  it("목록(GET): 부작용 없이 필요한 필드만 전달", async () => {
    const res = await list.GET(new Request(`${ORIGIN}/api/x`), ctx);
    const body = await res.json();
    expect(res.status).toBe(200);
    expect(body.items[0].id).toBe(RUN.id);
    expect(JSON.stringify(body)).not.toContain("secret");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("견적(POST): 키 필수·입력 검증·트림된 본문 전달, 201", async () => {
    expect((await list.POST(post(QUOTE, ORIGIN, null), ctx)).status).toBe(400);
    expect((await list.POST(post({ ...QUOTE, duration_sec: 16 }, ORIGIN, KEY), ctx)).status).toBe(400);
    expect((await list.POST(post({ ...QUOTE, prompt: "  " }, ORIGIN, KEY), ctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
    const res = await list.POST(post(QUOTE, ORIGIN, KEY), ctx);
    expect(res.status).toBe(201);
    expect((await res.json()).budget.monthly_left_krw).toBe(50000);
    expect(h.calls).toEqual([`quote:${ID}:${KEY}:${JSON.stringify({ source_asset_id: QUOTE.source_asset_id, prompt: "천천히 줌인", duration_sec: 5 })}`]);
  });

  it("확인·진행 확인·검수: 다른 출처는 403이고 API 호출 없음", async () => {
    for (const r of [confirmRoute, refreshRoute, reviewRoute]) expect((await r.POST(post({}, "https://evil.com"), rctx)).status).toBe(403);
    expect(h.calls).toHaveLength(0);
  });

  it("확인(202)·진행 확인(200) 정상 호출", async () => {
    expect((await confirmRoute.POST(post(), rctx)).status).toBe(202);
    const r = await refreshRoute.POST(post(), rctx);
    expect(r.status).toBe(200);
    expect((await r.json()).run.status).toBe("done");
    expect(h.calls).toEqual([`confirm:${ID}:${RUN.id}`, `refresh:${ID}:${RUN.id}`]);
  });

  it("검수: 3항목 boolean이 아니면 400, 맞으면 전달", async () => {
    expect((await reviewRoute.POST(post({ physics: true, angle: true }), rctx)).status).toBe(400);
    expect(h.calls).toHaveLength(0);
    const c = { physics: true, angle: true, compare: true };
    const res = await reviewRoute.POST(post(c), rctx);
    expect((await res.json()).reviewed).toBe(true);
    expect(h.calls).toEqual([`review:${ID}:${RUN.id}:${JSON.stringify(c)}`]);
  });

  it("403은 owner 안내, 409는 field 보존, 503은 사용 안 함 고정 문구(업스트림 사유 숨김)", async () => {
    h.fail = { status: 403, code: "FORBIDDEN", message: "upstream detail" };
    const f = await confirmRoute.POST(post(), rctx);
    expect(f.status).toBe(403);
    expect((await f.json()).message).toContain("소유자");
    h.fail = { status: 409, code: "CONFLICT", message: "예산을 넘었습니다.", field: "budget_exceeded" };
    const c = await list.POST(post(QUOTE, ORIGIN, KEY), ctx);
    expect(c.status).toBe(409);
    expect((await c.json()).field).toBe("budget_exceeded");
    h.fail = { status: 503, code: "UNAVAILABLE", message: "upstream detail" };
    const u = await list.POST(post(QUOTE, ORIGIN, KEY), ctx);
    expect(u.status).toBe(503);
    expect(JSON.stringify(await u.json())).not.toContain("upstream detail");
  });
});

describe("브라우저 호출", () => {
  it("5개 경로·메서드·견적 Idempotency-Key", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }));
    const ff = f as unknown as typeof fetch;
    await api.listGeneration(ID, ff);
    await api.quoteGeneration(ID, { source_asset_id: "s", prompt: "p", duration_sec: 3 }, KEY, ff);
    await api.confirmGeneration(ID, "r1", ff);
    await api.refreshGeneration(ID, "r1", ff);
    await api.reviewGeneration(ID, "r1", { physics: true, angle: true, compare: true }, ff);
    const seen = (f.mock.calls as unknown as [string, RequestInit][]).map(([u, i]) => `${i.method} ${u}`);
    const base = `/api/production-jobs/${ID}/generation-runs`;
    expect(seen).toEqual([`GET ${base}`, `POST ${base}`, `POST ${base}/r1/confirm`, `POST ${base}/r1/refresh`, `POST ${base}/r1/review`]);
    expect(((f.mock.calls as unknown as [string, RequestInit][])[1][1].headers as Record<string, string>)["Idempotency-Key"]).toBe(KEY);
  });
});

describe("순수 규칙(키 유지·이중 호출 차단·검수 가드)", () => {
  const body = { source_asset_id: "s", prompt: "p", duration_sec: 5 };

  it("견적 키: 5xx·네트워크 실패 뒤 재시도는 같은 키, 성공 뒤·입력 변경은 새 키", async () => {
    let n = 0;
    const runner = createIntentRunner(() => `k${++n}`);
    const keys: string[] = [];
    const send = (ok: boolean, status = 500) => (key: string) => {
      keys.push(key);
      return Promise.resolve(ok ? { ok: true as const } : { ok: false as const, keepKey: status === 0 || status >= 500 });
    };
    const fp = logic.quoteFingerprint(body);
    await runner.run(fp, send(false, 500));
    await runner.run(fp, send(false, 0));
    await runner.run(fp, send(true));
    await runner.run(fp, send(true));
    await runner.run(logic.quoteFingerprint({ ...body, duration_sec: 6 }), send(true));
    expect(keys).toEqual(["k1", "k1", "k1", "k2", "k3"]);
  });

  it("실행 중 이중 호출은 null이고 실제 요청은 1번", async () => {
    const f = logic.createSingleFlight();
    let calls = 0;
    let release: () => void = () => {};
    const first = f.run(() => new Promise<string>((res) => { calls++; release = () => res("a"); }));
    expect(f.busy).toBe(true);
    expect(await f.run(async () => { calls++; return "b"; })).toBeNull();
    release();
    expect(await first).toBe("a");
    expect(calls).toBe(1);
    expect(f.busy).toBe(false);
    expect(await f.run(async () => "c")).toBe("c");
    const runner = createIntentRunner();
    let q = 0;
    const slow = runner.run("x", () => new Promise<{ ok: boolean }>((res) => { q++; setTimeout(() => res({ ok: true }), 5); }));
    expect(await runner.run("x", async () => ({ ok: true }))).toBeNull();
    await slow;
    expect(q).toBe(1);
  });

  it("검수 가드: 3항목 모두 + 다른 요청 없음일 때만 저장", () => {
    const all = { physics: true, angle: true, compare: true };
    expect(logic.canSubmitReview(all, false)).toBe(true);
    expect(logic.canSubmitReview(all, true)).toBe(false);
    expect(logic.canSubmitReview({ ...all, angle: false }, false)).toBe(false);
    expect(logic.canSubmitReview(logic.NO_CHECKS, false)).toBe(false);
  });

  it("실패 뒤 목록 재조회: 확인은 항상, 견적은 5xx·네트워크만", () => {
    expect(logic.shouldReloadRuns("confirm", { ok: false, keepKey: false })).toBe(true);
    expect(logic.shouldReloadRuns("quote", { ok: false, keepKey: true })).toBe(true);
    expect(logic.shouldReloadRuns("quote", { ok: false, keepKey: false })).toBe(false);
    expect(logic.shouldReloadRuns("confirm", { ok: true })).toBe(false);
  });
});

describe("결과·입력 보기 relay", () => {
  it("done run의 result만 열고, 아니면 404", async () => {
    const route = await import("@/app/api/production-jobs/[id]/generation-runs/[runId]/asset-url/route");
    h.fail = null;
    const get = (which: string) => route.GET(new Request(`${ORIGIN}/api/x?which=${which}`), rctx);
    expect((await get("bad")).status).toBe(400);
    expect((await get("source")).status).toBe(200);
    expect((await get("result")).status).toBe(404); // RUN은 quoted
  });
});

describe("화면 조각", () => {
  it("상태 7종 한국어 표기, 진행 확인은 진행 중 상태만", () => {
    expect(Object.keys(gen.GEN_STATUS_LABEL).sort()).toEqual(["confirmed", "done", "failed", "finalizing", "quoted", "running", "unknown"]);
    expect(gen.isRefreshable("running")).toBe(true);
    expect(gen.isRefreshable("unknown")).toBe(true);
    expect(gen.isRefreshable("done")).toBe(false);
    expect(gen.isRefreshable("quoted")).toBe(false);
  });

  it("입력 검증: 프롬프트 1~500·길이 1~15", () => {
    expect(gen.validateGen("a", 1)).toEqual({});
    expect(gen.validateGen(" ", 5).prompt).toBeTruthy();
    expect(gen.validateGen("a".repeat(501), 5).prompt).toBeTruthy();
    expect(gen.validateGen("a", 0).duration).toBeTruthy();
    expect(gen.validateGen("a", 16).duration).toBeTruthy();
  });

  it("확인 모달: 예상 비용·월/작업 잔액·owner 안내·확인/취소", () => {
    const html = renderToStaticMarkup(<gen.ConfirmDialog est={1200} budget={{ monthly_left_krw: 50000, job_left_krw: 9000 }} busy={false} error={null} onConfirm={() => {}} onCancel={() => {}} />);
    expect(html).toContain("1,200원");
    expect(html).toContain("50,000원");
    expect(html).toContain("9,000원");
    expect(html).toContain("소유자");
    expect(html).toContain("생성 확인");
    expect(html).toContain("취소");
  });

  it("확인 모달 오류(403 안내)는 alert로 표시", () => {
    const html = renderToStaticMarkup(<gen.ConfirmDialog est={1} budget={null} busy={false} error="소유자만 할 수 있습니다." onConfirm={() => {}} onCancel={() => {}} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("소유자만 할 수 있습니다.");
  });

  it("검수 저장은 3항목이 모두 체크돼야 활성", () => {
    const view = (checks: Record<"physics" | "angle" | "compare", boolean>) => renderToStaticMarkup(<gen.ReviewChecks idPrefix="x" checks={checks} busy={false} onChange={() => {}} onSubmit={() => {}} />);
    expect(gen.REVIEW_ITEMS).toHaveLength(3);
    expect(view({ physics: true, angle: true, compare: false })).toMatch(/disabled="">검수 완료 저장/);
    expect(view({ physics: true, angle: true, compare: true })).not.toMatch(/disabled="">검수 완료 저장/);
    expect(gen.allChecked({ physics: true, angle: true, compare: false })).toBe(false);
    expect(gen.allChecked({ physics: true, angle: true, compare: true })).toBe(true);
  });
});
