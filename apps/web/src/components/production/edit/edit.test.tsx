import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { EditForm } = await import("./edit-form");
const model = await import("./model");
const api = await import("./api");
const { openSheetWindow } = await import("./sheet-panel");

const JOB = { id: "00000000-0000-4000-8000-0000000000e1", title: "작업", status: "review" as const, failed_stage: null };
const spec = (over: Record<string, unknown> = {}) => ({
  lang: "ko",
  header: { lines: ["첫째 줄", "둘째 줄"] },
  hook: { text: "훅 <b>문구</b>", tts: { voice: "ko-KR-SunHiNeural", rate: "+50%" } },
  duration: 6,
  shots: [
    { start: 0, end: 3, scale: 1.2, y: 0 },
    { start: 4, end: 6, scale: 1.2, y: 0 },
  ],
  items: [
    { start: 0, end: 1, kind: "white", text: "짧은 자막", y: 400 },
    { start: 1, end: 6, kind: "emph", text: "긴 자막" },
  ],
  overlays: [{ kind: "comment", text: "c", start: 0, end: 1, x: 1, y: 1 }],
  ...over,
});
const rev = (over: Record<string, unknown> = {}) => ({ rev_no: 2, spec: spec(), validation: { errors: [], warnings: [] }, approved_at: null, updated_at: "2026-11-02T00:00:00.123456Z", ...over });
const render = (revision: ReturnType<typeof rev> | null, job = JOB) =>
  renderToStaticMarkup(<EditForm job={job} revision={revision} sheet={{ jobId: job.id, sheetIds: ["s1"], sourceStart: 5, segmentLen: 30, sourceDuration: 120 }} />);
const ERR = { code: "shots.gap", path: "shots.1", message: "구도는 공백·겹침 없이 이어져야 합니다." };

describe("편집안 화면", () => {
  it("검증 오류·경고를 표시하고 오류가 있으면 승인을 막고 사유 링크를 보인다", () => {
    const html = render(rev({ validation: { errors: [ERR], warnings: [{ code: "items.too_short", path: "items.0", message: "표시 1.4초 미만입니다." }] } }));
    expect(html).toContain("검증 오류 1건");
    expect(html).toContain("구도 공백");
    expect(html).toContain("경고 1건");
    expect(html).toMatch(/<button type="button" disabled=""[^>]*aria-describedby="approve-why"[^>]*>승인<\/button>/);
    expect(html).toContain('href="#edit-issues"');
  });

  it("오류 0·저장 완료면 승인이 활성이고 사유가 없다", () => {
    const html = render(rev());
    expect(html).not.toContain("approve-why");
    expect(html).toMatch(/<button type="button" class="[^"]*">승인<\/button>/);
  });

  it("승인된 리비전·비편집 상태는 승인 불가 사유를 보인다", () => {
    expect(render(rev({ approved_at: "2026-11-19T01:00:00Z" }))).toContain("이미 승인된 편집안");
    const html = render(rev(), { ...JOB, status: "rendering" as never });
    expect(html).toContain("현재 상태에서는 편집안을 고칠 수 없습니다.");
    expect(html).toContain("편집안 검토 상태에서만 승인할 수 있습니다.");
  });

  it("초안이 없으면 빈 양식·안내를 보이고 저장·승인은 비활성", () => {
    const html = render(null);
    expect(html).toContain("편집안 초안이 아직 없습니다");
    expect(html).toMatch(/<button type="submit" disabled=""/);
  });

  it("문구는 이스케이프되고 1.4초 미만 자막에 노랑 배지가 붙는다", () => {
    const html = render(rev());
    expect(html).not.toContain("<b>문구</b>");
    expect(html).toContain("&lt;b&gt;문구&lt;/b&gt;");
    expect(html).toContain("1.4초 미만");
    expect(html).toContain("분석 시트");
    expect(html).toContain("시트 1 보기");
  });
});

describe("model", () => {
  it("spec ↔ draft 왕복에서 overlays 등 다른 필드를 보존한다", () => {
    const s = spec();
    const built = model.buildSpec(model.toDraft(s));
    expect(built).toEqual({ ok: true, spec: s });
  });

  it("숫자가 아닌 칸은 보내지 않고 위치를 돌려준다", () => {
    const d = model.toDraft(spec());
    d.shots[1].scale = "abc";
    expect(model.buildSpec(d)).toMatchObject({ ok: false, path: "shots.1.scale" });
    d.shots[1].scale = "1";
    d.duration = "NaN";
    expect(model.buildSpec(d)).toMatchObject({ ok: false, path: "duration" });
  });

  it("음성 첨부 시 tts는 빠진다", () => {
    const d = { ...model.toDraft(spec()), audioAssetId: "asset-1", tts: null };
    const built = model.buildSpec(d);
    expect(built.ok && (built.spec.hook as Record<string, unknown>)).toEqual({ text: "훅 <b>문구</b>", audio_asset_id: "asset-1" });
  });

  it("타임라인: 공백·겹침은 bad, 1.4초 미만 자막은 short", () => {
    const d = model.toDraft(spec());
    expect(model.shotSegments(d.shots, 6).map((s) => s.bad)).toEqual([false, true]);
    expect(model.itemSegments(d.items, 6).map((s) => s.short)).toEqual([true, false]);
    expect(model.shotSegments(d.shots, 0)).toEqual([]);
  });

  it("승인 사유: 미저장·오류·상태", () => {
    const base = { status: "review" as const, hasRevision: true, dirty: false, approved: false, errorCount: 0, busy: false };
    expect(model.approveBlockers(base)).toEqual([]);
    expect(model.approveBlockers({ ...base, dirty: true, errorCount: 2 }).map((b) => b.id)).toEqual(["dirty", "errors"]);
    expect(model.isEditableStatus("failed", "render")).toBe(true);
    expect(model.isEditableStatus("failed", "prepare")).toBe(false);
  });

  it("issuesAt은 행과 하위 필드를 모은다", () => {
    const list = [ERR, { code: "x", path: "shots.10", message: "m" }, { code: "y", path: "shots.1.scale", message: "m" }];
    expect(model.issuesAt(list, "shots.1").map((i) => i.code)).toEqual(["shots.gap", "y"]);
  });
});

describe("api", () => {
  const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
  it("400 응답의 errors·warnings를, 409는 상태 코드를 보존한다", async () => {
    const f400 = (async () => res(400, { message: "오류", errors: [ERR], warnings: [] })) as unknown as typeof fetch;
    const r = await api.saveRevision(JOB.id, {}, 1, "t", f400);
    expect(r).toMatchObject({ ok: false, status: 400, errors: [ERR], warnings: [] });
    const f409 = (async () => res(409, { message: "충돌" })) as unknown as typeof fetch;
    expect(await api.approveRevision(JOB.id, 1, f409)).toMatchObject({ ok: false, status: 409, message: "충돌" });
  });

  it("음성 확장자만 허용한다", () => {
    expect(api.audioMime({ name: "a.WAV" })).toBe("audio/wav");
    expect(api.audioMime({ name: "a.exe" })).toBeNull();
  });
});

describe("openSheetWindow", () => {
  const win = () => ({ opener: "x" as unknown, location: { href: "" }, close: vi.fn() });
  it("빈 창을 먼저 열고 opener를 끊은 뒤 URL로 이동, 실패하면 창을 닫고 문구를 돌려준다", async () => {
    const w = win();
    const open = vi.fn(() => w) as unknown as typeof window.open;
    expect(await openSheetWindow("j", "a", async () => ({ ok: true, data: { url: "https://s/get" } }), open)).toBeNull();
    expect(open).toHaveBeenCalledWith("", "_blank");
    expect(w.opener).toBeNull();
    expect(w.location.href).toBe("https://s/get");

    const w2 = win();
    const msg = await openSheetWindow("j", "a", async () => ({ ok: false, status: 404, message: "없음" }), (() => w2) as unknown as typeof window.open);
    expect(msg).toBe("없음");
    expect(w2.close).toHaveBeenCalled();
  });
});

describe("task-059 저장 잠금(ko)", () => {
  const AT = "2026-11-02T00:00:00.123456Z";
  it("반환 updated_at으로 연속 저장 2회 성공, 낡은 base는 409", async () => {
    const { lockServer } = await import("../lock-server.test-util");
    const srv = lockServer({ rev_no: 2, updated_at: AT, approved: false });
    const r1 = await api.saveRevision(JOB.id, {}, 2, AT, srv.f);
    if (!r1.ok) throw new Error("r1");
    const r2 = await api.saveRevision(JOB.id, {}, r1.data.revision.rev_no, r1.data.revision.updated_at, srv.f);
    expect(r2.ok).toBe(true);
    expect(await api.saveRevision(JOB.id, {}, 2, AT, srv.f)).toMatchObject({ ok: false, status: 409 });
    expect(srv.sent[0]).toBe(AT); // 마이크로초 문자열 그대로(Date 변환 없음)
  });
  it("승인본 저장도 낡은 base면 409, 맞으면 새 rev", async () => {
    const { lockServer } = await import("../lock-server.test-util");
    const srv = lockServer({ rev_no: 2, updated_at: AT, approved: true });
    expect(await api.saveRevision(JOB.id, {}, 2, "2026-11-02T00:00:00.123457Z", srv.f)).toMatchObject({ ok: false, status: 409 });
    const ok = await api.saveRevision(JOB.id, {}, 2, AT, srv.f);
    expect(ok.ok && ok.data.revision.rev_no).toBe(3);
  });
});
