import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProductionJobDetail } from "@/server/api/production";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { RunView } = await import("./run-view");
const model = await import("./model");
const api = await import("./api");

const ID = "00000000-0000-4000-8000-0000000000e1";
type Over = {
  status?: ProductionJobDetail["job"]["status"];
  failed_stage?: ProductionJobDetail["job"]["failed_stage"];
  approved?: boolean;
  run?: Partial<NonNullable<ProductionJobDetail["latest_run"]>> | null;
  assets?: ProductionJobDetail["assets"];
  online?: boolean;
};
const detail = (o: Over = {}): ProductionJobDetail =>
  ({
    job: { id: ID, title: "작업 <b>제목</b>", status: o.status ?? "review", failed_stage: o.failed_stage ?? null, error_code: null },
    assets: o.assets ?? [],
    current_revision: { ko: { id: "rev1", rev_no: 1, approved_at: o.approved === false ? null : "2026-11-19T01:00:00Z", validation: { errors: [], warnings: [] } }, ja: null },
    latest_run: o.run === null ? null : o.run ? { id: "run1", status: "running", progress_pct: 40, progress_stage: "render", error_stage: null, error_code: null, attempt: 1, ...o.run } : null,
    worker_online: o.online ?? true,
  }) as unknown as ProductionJobDetail;
const render = (o?: Over) => renderToStaticMarkup(<RunView detail={detail(o)} />);
const ASSETS = [
  { id: "m1", kind: "output_mp4", status: "ready" as const, size_bytes: 1, duration_sec: 6 },
  { id: "r1", kind: "report", status: "ready" as const, size_bytes: 1, duration_sec: null },
];

describe("PROD-03 상태별 버튼", () => {
  it("승인됨·렌더 미시작: 안내와 렌더 요청, 재시도·승인 없음", () => {
    const html = render();
    expect(html).toContain("승인됨 — 렌더 요청을 눌러 시작");
    expect(html).toMatch(/<button type="button" class="[^"]*">렌더 요청<\/button>/);
    expect(html).not.toContain("재시도");
    expect(html).not.toContain("검수 승인");
  });

  it("미승인이면 렌더 요청 대신 편집안 링크", () => {
    const html = render({ approved: false });
    expect(html).not.toContain(">렌더 요청<");
    expect(html).toContain(`/production/${ID}/edit`);
  });

  it("렌더 중: 비활성 버튼·진행률, 오프라인이면 워커 안내", () => {
    const html = render({ status: "rendering", run: {} });
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>렌더 중<\/button>/);
    expect(html).toContain("40%");
    expect(html).not.toContain("워커가 오프라인");
    expect(render({ status: "rendering", run: {}, online: false })).toContain("워커가 오프라인");
  });

  it("검수 대기: 영상·리포트·다운로드·검수 승인", () => {
    const html = render({ status: "inspect", run: { status: "done" }, assets: ASSETS });
    expect(html).toContain("검수 승인 → 완료");
    expect(html).toContain("MP4 다운로드");
    expect(html).toContain("리포트 열기");
    expect(html).toContain("편집안으로(새 리비전)");
  });

  it("완료: 검수 승인 버튼 없음", () => {
    const html = render({ status: "done", run: { status: "done" }, assets: ASSETS });
    expect(html).not.toContain("검수 승인");
    expect(html).toContain("MP4 다운로드");
  });
});

describe("PROD-03 실패 사유별 링크", () => {
  const failed = (code: string, extra: Over = {}) =>
    render({ status: "failed", failed_stage: "render", run: { status: "failed", error_stage: "render", error_code: code }, ...extra });

  it("일반 실패(worker_offline 포함): 재시도, 편집 링크 없음", () => {
    for (const code of ["worker_offline", "ffmpeg_failed"]) {
      const html = failed(code);
      expect(html).toContain(code);
      expect(html).toContain(">재시도</button>");
      expect(html).not.toContain("고치기");
    }
  });

  it("hook_too_long·text_too_long: 재시도 없이 편집안 링크", () => {
    for (const code of ["hook_too_long", "text_too_long"]) {
      const html = failed(code);
      expect(html).not.toContain(">재시도<");
      expect(html).toContain("편집안으로 돌아가 고치기");
      expect(html).toContain(`/production/${ID}/edit`);
    }
  });

  it("알 수 없는 실패 단계도 일반 실패 안내와 사유 코드를 보이고 run이 없으면 재시도 없음", () => {
    const html = render({ status: "failed", failed_stage: null, run: null });
    expect(html).toContain("실패 단계: 알 수 없음");
    expect(html).toContain("unknown");
    expect(html).not.toContain(">재시도<");
  });

  it("사유 코드는 이스케이프된다", () => {
    const html = failed("<script>x</script>");
    expect(html).not.toContain("<script>x");
    expect(html).toContain("&lt;script&gt;");
  });
});

describe("model.viewOf", () => {
  it("실패 run이 아니면 재시도하지 않는다", () => {
    const d = detail({ status: "failed", failed_stage: "render", run: { status: "running", error_code: "x" } });
    expect(model.viewOf(d).canRetry).toBe(false);
  });
  it("latestAsset은 가장 최근 ready 자산", () => {
    const a = [...ASSETS, { id: "m2", kind: "output_mp4", status: "ready" as const, size_bytes: 1, duration_sec: 1 }, { id: "m3", kind: "output_mp4", status: "pending" as const, size_bytes: null, duration_sec: null }];
    expect(model.latestAsset(a, "output_mp4")).toBe("m2");
    expect(model.latestAsset([], "report")).toBeNull();
  });
});

describe("api", () => {
  it("렌더 요청은 멱등 키 헤더·ko 본문", async () => {
    const key = ["k", "e", "y"].join("") + "-12345678";
    const f = vi.fn(async () => new Response(JSON.stringify({ run: { id: "r", status: "queued", attempt: 1 } }), { status: 202 }));
    const r = await api.requestRender(ID, "rev1", key, f as unknown as typeof fetch);
    expect(r.ok).toBe(true);
    const init = (f.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe(key);
    expect(JSON.parse(init.body as string)).toEqual({ revision_id: "rev1", lang: "ko" });
  });
  it("5xx·전송 실패는 키 유지, 4xx는 교체", async () => {
    const mk = (s: number) => vi.fn(async () => new Response(JSON.stringify({ message: "m" }), { status: s })) as unknown as typeof fetch;
    expect(await api.retryRender(ID, "r", mk(502))).toMatchObject({ ok: false, keepKey: true });
    expect(await api.retryRender(ID, "r", mk(409))).toMatchObject({ ok: false, keepKey: false, message: "m" });
  });
});
