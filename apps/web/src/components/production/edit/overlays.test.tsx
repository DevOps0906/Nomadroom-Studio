import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { OverlaysTab } from "./OverlaysTab";
import { approveBlockers, buildSpec, emptyDraft, toDraft, type OverlayDraft } from "./model";

const ov = (over: Partial<OverlayDraft> = {}): OverlayDraft => ({ kind: "comment", text: "<b>댓글</b>", start: "1", end: "3", x: "304", y: "200", ...over });
const html = (kind: "comment" | "source", overlays: OverlayDraft[], errors: { code: string; path: string; message: string }[] = [], warnings = errors.slice(0, 0)) =>
  renderToStaticMarkup(<OverlaysTab kind={kind} overlays={overlays} errors={errors} warnings={warnings} lock={false} onChange={() => {}} />);

describe("댓글·출처 탭", () => {
  it("종류별 행만 보이고 문구는 이스케이프된다", () => {
    const out = html("comment", [ov(), ov({ kind: "source", text: "출처문구" })]);
    expect(out).toContain("&lt;b&gt;댓글&lt;/b&gt;");
    expect(out).not.toContain("출처문구");
    expect(html("source", [ov(), ov({ kind: "source", text: "출처문구" })])).toContain("출처문구");
  });

  it("빈 상태 안내를 보인다", () => {
    expect(html("comment", [])).toContain("댓글 카드가 없습니다");
    expect(html("source", [])).toContain("출처 표기가 없습니다");
  });

  it("오류는 해당 행에, 자막 겹침은 경고로 표시한다", () => {
    const out = html("comment", [ov()], [{ code: "overlays.range", path: "overlays.0", message: "범위 초과" }], [{ code: "overlays.caption_overlap", path: "overlays.0", message: "자막 1과 겹칩니다." }]);
    expect(out).toContain("오버레이 구간 범위: 범위 초과");
    expect(out).toContain("자막과 겹침: 자막 1과 겹칩니다.");
  });

  it("전체 목록 기준 경로(overlays.N)로 오류를 맞춘다", () => {
    const out = html("source", [ov(), ov({ kind: "source", text: "s" })], [{ code: "overlays.pos", path: "overlays.1.x", message: "화면 밖" }]);
    expect(out).toContain("오버레이 위치 범위: 화면 밖");
  });
});

describe("overlays 모델", () => {
  it("왕복에서 값과 ref를 보존하고 빈 목록은 키를 보내지 않는다", () => {
    const spec = { lang: "ko", header: { lines: ["a", "b"] }, hook: { text: "h", audio_asset_id: "x" }, duration: 5, shots: [], items: [], overlays: [{ kind: "source", text: "t", start: 0, end: 2, x: 10, y: 20, ref: "r1" }] };
    expect(buildSpec(toDraft(spec))).toEqual({ ok: true, spec });
    const empty = buildSpec({ ...emptyDraft(), duration: "5" });
    expect(empty.ok && "overlays" in empty.spec).toBe(false);
  });

  it("숫자가 아닌 칸은 보내지 않고 위치를 돌려준다", () => {
    const d = { ...emptyDraft(), duration: "5", overlays: [ov({ x: "abc" })] };
    expect(buildSpec(d)).toMatchObject({ ok: false, path: "overlays.0.x" });
  });
});

describe("승인 사유·로컬 오류", () => {
  it("overlays 오류는 댓글·출처 탭 오류 N건으로 따로 센다", () => {
    const base = { status: "review" as const, hasRevision: true, dirty: false, approved: false, busy: false };
    const r = approveBlockers({ ...base, errorCount: 3, overlayErrorCount: 2 });
    expect(r.map((b) => b.id)).toEqual(["errors", "overlays"]);
    expect(r[1].text).toContain("댓글·출처 탭 오류 2건");
    expect(approveBlockers({ ...base, errorCount: 2, overlayErrorCount: 2 }).map((b) => b.id)).toEqual(["overlays"]);
  });

  it("OverlaysTab은 로컬 숫자 오류(overlays.N.x)를 해당 행에 표시한다", () => {
    const out = html("comment", [ov({ x: "abc" })], [{ code: "input.number", path: "overlays.0.x", message: "숫자를 입력하세요." }]);
    expect(out).toContain("숫자를 입력하세요.");
    expect(out).toContain('aria-invalid="true"');
  });
});
