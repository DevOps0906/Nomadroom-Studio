import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProductionJobDetail } from "@/server/api/production";

// task-033 인수 테스트(웹 쪽): CAT-08(오버레이·AI 초안·URL 원본) + TTS 실패 복귀 화면.
// 근거: Nomadroom_Category_Shorts_PRD.md#5 CAT-08, tasks/task-029~032.md.

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { EditForm } = await import("./edit/edit-form");
const editModel = await import("./edit/model");
const { buildSpec, toDraft } = editModel;
const { RunView } = await import("./run/run-view");
const runModel = await import("./run/model");

const ID = "00000000-0000-4000-8000-0000000000e8";
const COMMENT = { kind: "comment", text: "댓글 문구", start: 2, end: 6, x: 304, y: 200 };
const SOURCE = { kind: "source", text: "출처 문구", start: 0, end: 15, x: 304, y: 1000 };
const TTS = { voice: "ko-KR-SunHiNeural", rate: "+50%" };
const baseSpec = (hook: Record<string, unknown>, overlays: unknown[] = [COMMENT, SOURCE]) => ({
  lang: "ko",
  header: { lines: ["첫째 줄", "둘째 줄"] },
  hook,
  duration: 15,
  shots: [{ start: 0, end: 15, scale: 1, y: 0 }],
  items: [{ start: 0, end: 15, kind: "white", text: "자막" }],
  overlays,
});
const JOB = { id: ID, title: "작업", status: "review" as const, failed_stage: null };
const editHtml = (spec: Record<string, unknown>, approved: string | null = null) =>
  renderToStaticMarkup(
    <EditForm
      job={JOB}
      revision={{ rev_no: 1, spec, validation: { errors: [], warnings: [] }, approved_at: approved } as never}
      sheet={{ jobId: ID, sheetIds: ["s1"], sourceStart: 30, segmentLen: 15, sourceDuration: 15 }}
    />,
  );

describe("CAT-08 오버레이·편집안 왕복", () => {
  it("댓글·출처 오버레이와 TTS가 편집안 왕복에서 그대로 보존된다", () => {
    const spec = baseSpec({ text: "훅", tts: TTS });
    expect(buildSpec(toDraft(spec))).toEqual({ ok: true, spec });
  });

  it("첨부 음성으로 바꾼 편집안은 tts 키를 보내지 않고 오버레이는 유지한다(복귀 경로)", () => {
    const d = toDraft(baseSpec({ text: "훅", tts: TTS }));
    const swapped = { ...d, audioAssetId: "asset-1", tts: null };
    const r = buildSpec(swapped);
    expect(r.ok).toBe(true);
    const s = (r as unknown as { spec: { hook: Record<string, unknown>; overlays: unknown[] } }).spec;
    expect(s.hook).toEqual({ text: "훅", audio_asset_id: "asset-1" });
    expect(s.overlays).toEqual([COMMENT, SOURCE]);
  });

  it("TTS 속도·음성 형식이 서버 패턴과 다르면 보내지 않고 위치를 알려 준다", () => {
    const d = toDraft(baseSpec({ text: "훅", tts: TTS }));
    expect(buildSpec({ ...d, tts: { voice: TTS.voice, rate: "50" } })).toMatchObject({ ok: false, path: "hook.tts.rate" });
    expect(buildSpec({ ...d, tts: { voice: "x", rate: "+50%" } })).toMatchObject({ ok: false, path: "hook.tts.voice" });
  });

  it("TTS 음성 목록은 편집안 lang 접두사 음성만, 기본값도 lang에 맞는다", () => {
    expect(editModel.voicesFor("ko").every((v) => v.id.startsWith("ko-"))).toBe(true);
    expect(editModel.voicesFor("ja").every((v) => v.id.startsWith("ja-"))).toBe(true);
    expect(editModel.defaultTts("ja").voice.startsWith("ja-")).toBe(true);
    const html = editHtml(baseSpec({ text: "훅", tts: TTS }));
    expect(html).toContain("ko-KR-InJoonNeural");
    expect(html).not.toContain("ja-JP-NanamiNeural");
  });

  it("편집 화면에 AI 초안 버튼·댓글·출처 탭이 있다(review)", () => {
    const html = editHtml(baseSpec({ text: "훅", audio_asset_id: "a" }));
    expect(html).toContain("AI 초안 채우기");
    expect(html).toContain("댓글");
    expect(html).toContain("출처");
  });
});

const detail = (code: string, status = "failed") =>
  ({
    job: { id: ID, title: "작업", status, failed_stage: "audio", error_code: null },
    assets: [],
    current_revision: { ko: { id: "rev1", rev_no: 1, approved_at: "2026-11-19T01:00:00Z", validation: { errors: [], warnings: [] } }, ja: null },
    latest_run: { id: "run1", status: "failed", progress_pct: 0, progress_stage: "audio", error_stage: "audio", error_code: code, attempt: 1 },
    worker_online: true,
  }) as unknown as ProductionJobDetail;

describe("TTS 실패 복귀 화면(tts_failed)", () => {
  it("편집안으로 돌아가 고치기 링크와 첨부 음성 안내가 있고 재시도 버튼은 없다", () => {
    const html = renderToStaticMarkup(<RunView detail={detail("tts_failed")} />);
    expect(html).toContain("편집안으로 돌아가 고치기");
    expect(html).toContain(`/production/${ID}/edit`);
    expect(html).toContain(runModel.REASON_TEXT.tts_failed!);
    expect(html).toContain("첨부 음성");
    expect(html).not.toContain(">재시도<");
  });

  it("실제 API 상태(job=review, latest_run=tts_failed)에서도 실패 사유와 편집 링크를 보인다", () => {
    const html = renderToStaticMarkup(<RunView detail={detail("tts_failed", "review")} />);
    expect(html).toContain(runModel.REASON_TEXT.tts_failed!);
    expect(html).toContain("편집안으로 돌아가 고치기");
  });

  it("편집 사유 실패(review 복귀)에는 렌더 요청 섹션을 숨기고 링크는 하나만 둔다", () => {
    const html = renderToStaticMarkup(<RunView detail={detail("hook_too_long", "review")} />);
    expect(html).not.toContain(">렌더 요청<");
    expect(html.split("편집안으로 돌아가 고치기").length - 1).toBe(1);
    expect(html).toMatch(/\d+초/);
  });

  it("tts_failed는 편집 우선 코드다(자동 재시도 대상 아님)", () => {
    expect(runModel.EDIT_FIRST_CODES).toContain("tts_failed");
  });

  it("TTS 편집안을 열면 현재 TTS 사용 안내와 첨부 전환 힌트가 보인다", () => {
    const html = editHtml(baseSpec({ text: "훅", tts: TTS }), "2026-11-19T01:00:00Z");
    expect(html).toContain("현재 TTS 음성을 쓰고 있습니다");
    expect(html).toContain("파일을 올리면 첨부 음성으로 바뀝니다");
  });

  it("편집 화면에서 TTS 음성(voice)을 선택할 수 있다", () => {
    const html = editHtml(baseSpec({ text: "훅", audio_asset_id: "a" }));
    expect(html).toMatch(/TTS[^<]{0,20}(음성|목소리)|<select[^>]*(voice|tts)/i);
  });

  it("편집 화면에서 TTS 속도(rate)를 조정할 수 있다", () => {
    const html = editHtml(baseSpec({ text: "훅", tts: TTS }));
    expect(html).toMatch(/속도|id="ed-tts-rate"|name="rate"/);
  });
});
