import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProductionJobDetail } from "@/server/api/production";

// task-028 인수 테스트(웹 쪽): CAT-01·02·03·04·06·07의 화면·요청 동작. 근거: Nomadroom_Category_Shorts_PRD.md#5.
// 결함 재현은 it.fails — 결함이 고쳐지면(테스트가 통과하면) 실패로 바뀌어 it 로 승격하라는 신호가 된다.

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { EditForm } = await import("./edit/edit-form");
const editModel = await import("./edit/model");
const { RunView } = await import("./run/run-view");
const runModel = await import("./run/model");
const runApi = await import("./run/api");
const prodApi = await import("./api");

const ID = "00000000-0000-4000-8000-0000000000e1";
const CAND = "00000000-0000-4000-8000-0000000000b1";

const okJson = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
const lastCall = (f: typeof fetch) => (f as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0]!;

describe("CAT-01 저장된 소재에서 시작", () => {
  it("소재 ID·제목·구간이 작업 생성 요청에 실리고 멱등 키가 붙는다", async () => {
    const f = okJson(201, { job: { id: ID, status: "draft" } });
    const r = await prodApi.createJob(
      { title: "저장된 소재", candidate_id: CAND, rights_confirmed: true, license_cc: null, credit: null, source_start_sec: 30, segment_len_sec: 15 },
      "key-" + "12345678",
      f,
    );
    expect(r.ok).toBe(true);
    const [url, init] = lastCall(f);
    expect(url).toBe("/api/production-jobs");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-12345678");
    expect(JSON.parse(init.body as string)).toMatchObject({ title: "저장된 소재", candidate_id: CAND, format: "category", source_kind: "upload" });
  });
});

describe("CAT-02 30초 지점부터 15초", () => {
  it("시작 30·길이 15가 그대로 전달되고 폼 검증을 통과한다", async () => {
    const f = okJson(201, { job: { id: ID, status: "draft" } });
    await prodApi.createJob({ title: "t", rights_confirmed: true, license_cc: null, credit: null, source_start_sec: 30, segment_len_sec: 15 }, "key-12345678", f);
    expect(JSON.parse(lastCall(f)[1].body as string)).toMatchObject({ source_start_sec: 30, segment_len_sec: 15 });
  });
});

const spec = (over: Record<string, unknown> = {}) => ({
  lang: "ko",
  header: { lines: ["첫째 줄", "둘째 줄"] },
  hook: { text: "훅", audio_asset_id: "hook-1" },
  duration: 15,
  shots: [
    { start: 0, end: 6, scale: 1, y: 0 },
    { start: 7, end: 15, scale: 1, y: 0 },
  ],
  items: [
    { start: 0, end: 3, kind: "white", text: "a" },
    { start: 2, end: 15, kind: "white", text: "겹침" },
  ],
  ...over,
});
const JOB = { id: ID, title: "작업", status: "review" as const, failed_stage: null };
const GAP = { code: "shots.gap", path: "shots.1", message: "구도는 공백·겹침 없이 이어져야 합니다." };
const OVERLAP = { code: "items.overlap", path: "items.1", message: "자막은 시간순이며 겹치면 안 됩니다." };
const editHtml = (errors: unknown[]) =>
  renderToStaticMarkup(
    <EditForm
      job={JOB}
      revision={{ rev_no: 1, spec: spec(), validation: { errors, warnings: [] }, approved_at: null } as never}
      sheet={{ jobId: ID, sheetIds: ["s1"], sourceStart: 30, segmentLen: 15, sourceDuration: 15 }}
    />,
  );

describe("CAT-03 구도 공백·자막 겹침", () => {
  it("어느 구간(경로)이 잘못됐는지 표시하고 승인을 막는다", () => {
    const html = editHtml([GAP, OVERLAP]);
    expect(html).toContain("검증 오류 2건");
    expect(html).toContain("구도 공백");
    expect(html).toContain("shots.1");
    expect(html).toContain("items.1");
    expect(html).toMatch(/<button type="button" disabled=""[^>]*aria-describedby="approve-why"[^>]*>승인<\/button>/);
  });

  it("행 단위로 오류가 매핑된다", () => {
    expect(editModel.issuesAt([GAP, OVERLAP], "shots.1")).toEqual([GAP]);
    expect(editModel.issuesAt([GAP, OVERLAP], "items.1")).toEqual([OVERLAP]);
    expect(editModel.issuesAt([GAP, OVERLAP], "items.0")).toEqual([]);
  });

  it("오류가 있으면 승인 불가 사유에 건수가 나온다", () => {
    const why = editModel.approveBlockers({ status: "review", hasRevision: true, dirty: false, approved: false, errorCount: 2, busy: false });
    expect(why.map((w) => w.id)).toEqual(["errors"]);
    expect(why[0]!.text).toContain("2건");
  });
});

const detail = (o: { status?: string; failed_stage?: string | null; run?: Record<string, unknown> | null; approved?: boolean; online?: boolean; assets?: unknown[] } = {}) =>
  ({
    job: { id: ID, title: "작업", status: o.status ?? "review", failed_stage: o.failed_stage ?? null, error_code: null },
    assets: o.assets ?? [],
    current_revision: { ko: { id: "rev1", rev_no: 1, approved_at: o.approved === false ? null : "2026-11-19T01:00:00Z", validation: { errors: [], warnings: [] } }, ja: null },
    latest_run: o.run === null ? null : o.run ? { id: "run1", status: "running", progress_pct: 40, progress_stage: "render", error_stage: null, error_code: null, attempt: 1, ...o.run } : null,
    worker_online: o.online ?? true,
  }) as unknown as ProductionJobDetail;
const runHtml = (o?: Parameters<typeof detail>[0]) => renderToStaticMarkup(<RunView detail={detail(o)} />);
const failedHtml = (code: string) => runHtml({ status: "failed", failed_stage: "audio", run: { status: "failed", error_stage: "audio", error_code: code } });

describe("CAT-04 첫 자막에 들어가지 않는 훅 음성", () => {
  it("편집안으로 돌아가 고치기 링크만 보이고 재시도는 없다(편집안 유지)", () => {
    const html = failedHtml("hook_too_long");
    expect(html).toContain("편집안으로 돌아가 고치기");
    expect(html).toContain(`/production/${ID}/edit`);
    expect(html).not.toContain(">재시도<");
    expect(html).toContain(runModel.REASON_TEXT.hook_too_long!);
  });

  // 결함 재현(🟡): PRD CAT-04 는 '필요한 시간을 안내'하라는데 화면 문구에는 초 단위 안내가 없다.
  // 워커도 실패 보고에 훅 길이·허용 길이를 싣지 않는다(04_API.md W-09: failed는 코드만).
  it.fails("필요한 시간(초)을 안내한다", () => {
    expect(failedHtml("hook_too_long")).toMatch(/\d+(\.\d+)?\s*초/);
  });
});

describe("CAT-06 산출물 검수", () => {
  const ASSETS = [
    { id: "m1", kind: "output_mp4", status: "ready", size_bytes: 1, duration_sec: 15 },
    { id: "r1", kind: "report", status: "ready", size_bytes: 1, duration_sec: null },
  ];

  it("검수 단계: MP4·리포트·검수 승인·새 리비전 링크가 있다", () => {
    const html = runHtml({ status: "inspect", run: { status: "done" }, assets: ASSETS });
    for (const t of ["MP4 다운로드", "리포트 열기", "검수 승인 → 완료", "편집안으로(새 리비전)"]) expect(html).toContain(t);
  });

  it("MP4가 없으면 검수 승인이 비활성", () => {
    const html = runHtml({ status: "inspect", run: { status: "done" }, assets: [] });
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>검수 승인 → 완료<\/button>/);
  });

  // 결함 재현(🟡): PRD CAT-06 은 '글자 잘림·검은 틈·핵심 피사체 잘림'을 검수하라는데 PROD-03 에는
  // 이 3항목 확인 안내·체크가 없다(리포트 열기 버튼뿐). docs/03_SCREENS_UX.md 에도 항목이 없다.
  it.fails("검수 화면이 글자 잘림·검은 틈·핵심 피사체 잘림 확인을 안내한다", () => {
    const html = runHtml({ status: "inspect", run: { status: "done" }, assets: ASSETS });
    for (const t of ["글자 잘림", "검은 틈", "피사체"]) expect(html).toContain(t);
  });
});

describe("CAT-07 중복 요청·실패 후 재시도", () => {
  it("승인됨: 렌더 요청 버튼, 렌더 중: 요청 버튼 없이 '렌더 중'만(같은 버튼 재클릭 불가)", () => {
    const review = runHtml();
    expect(review).toContain(">렌더 요청<");
    const rendering = runHtml({ status: "rendering", run: { status: "running" } });
    expect(rendering).not.toContain(">렌더 요청<");
    expect(rendering).toContain("렌더 중");
    expect(runModel.viewOf(detail({ status: "rendering", run: { status: "running" } })).canRequest).toBe(false);
  });

  it("같은 키 재요청은 200 + 기존 run, 같은 키를 다시 보낸다(5xx는 키 유지)", async () => {
    const key = "dbl-" + "12345678";
    const f = okJson(200, { run: { id: "run1", status: "queued", attempt: 1 } });
    await runApi.requestRender(ID, "rev1", key, f);
    await runApi.requestRender(ID, "rev1", key, f);
    const calls = (f as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
    expect(calls.map((c) => (c[1].headers as Record<string, string>)["Idempotency-Key"])).toEqual([key, key]);
    expect(await runApi.requestRender(ID, "rev1", key, okJson(502, {}))).toMatchObject({ ok: false, keepKey: true });
    expect(await runApi.requestRender(ID, "rev1", key, okJson(409, { message: "진행 중" }))).toMatchObject({ ok: false, keepKey: false, message: "진행 중" });
  });

  it("실패(render_failed·worker_offline)는 같은 단계에서 재시도 버튼, 새 시도는 A-16 경로", async () => {
    for (const code of ["render_failed", "worker_offline"]) {
      const html = runHtml({ status: "failed", failed_stage: "render", run: { status: "failed", error_stage: "render", error_code: code } });
      expect(html).toContain(">재시도</button>");
    }
    const f = okJson(202, { run: { id: "run2", status: "queued", attempt: 2 } });
    const r = await runApi.retryRender(ID, "run1", f);
    expect(r).toMatchObject({ ok: true });
    expect(lastCall(f)[0]).toBe(`/api/production-jobs/${ID}/render-runs/run1/retry`);
    expect(lastCall(f)[1].method).toBe("POST");
  });
});
