import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// task-056 PROD-02S AI 대본 3안 UI(고지·3안 카드·이 안 사용·narration_stale).

vi.mock("server-only", () => ({}));

const { AiScriptPanel, AiScriptResult, AI_SCRIPT_DISCLOSURE, NARRATION_STALE_NOTE, applyVariant, hasNarrationStale } = await import("./ai-script");
const { emptyShoppingDraft } = await import("./model");

const VARIANTS = [
  { hook_type: "질문형", sentences: ["하나", "둘", "셋", "넷"], char_count: 4 },
  { hook_type: "공감형", sentences: ["[확인 필요] 가격 9,900원", "둘", "셋", "넷"], char_count: 20 },
  { hook_type: "<script>alert(1)</script>", sentences: ["a", "b", "c", "d"], char_count: 4 },
];

describe("AiScriptPanel", () => {
  const props = { jobId: "j1", dirty: false, onBusy: () => {}, onApplied: () => {}, onUse: () => {}, onFail: () => {} };

  it("실행 전에 외부 AI 전송 고지가 있다", () => {
    const html = renderToStaticMarkup(<AiScriptPanel {...props} disabled={false} />);
    expect(html).toContain("AI 대본 3안 만들기");
    expect(html).toContain(AI_SCRIPT_DISCLOSURE);
    expect(AI_SCRIPT_DISCLOSURE).toBe("브리프 텍스트가 외부 AI(Claude)로 전송됩니다.");
  });

  it("비활성이면 버튼이 disabled", () => {
    expect(renderToStaticMarkup(<AiScriptPanel {...props} disabled />)).toMatch(/<button type="button" disabled=""/);
  });
});

describe("AiScriptResult", () => {
  const base = { variants: VARIANTS, facts: ["성분 표기 확인", "가격 확인"], staleNarration: false, disabled: false, usedIndex: 0, onUse: () => {} };

  it("3안 카드: 후킹 유형·문장·글자 수·[확인 필요] 배지·이 안 사용", () => {
    const html = renderToStaticMarkup(<AiScriptResult {...base} />);
    expect(html).toContain("1안 · 질문형");
    expect(html).toContain("2안 · 공감형");
    expect(html).toContain("20자");
    expect(html.match(/이 안 사용/g)?.length).toBe(2);
    expect(html).toContain("사용 중");
    expect(html).toContain("rounded-chip");
    expect(html).toContain("업로드 전 확인할 사실");
    expect(html).toContain("성분 표기 확인");
  });

  it("AI 텍스트는 이스케이프된다", () => {
    const html = renderToStaticMarkup(<AiScriptResult {...base} />);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("narration_stale 안내", () => {
    expect(renderToStaticMarkup(<AiScriptResult {...base} staleNarration />)).toContain(NARRATION_STALE_NOTE);
    expect(renderToStaticMarkup(<AiScriptResult {...base} />)).not.toContain(NARRATION_STALE_NOTE);
    expect(hasNarrationStale([{ code: "voice.narration_stale" }])).toBe(true);
    expect(hasNarrationStale([{ code: "other" }])).toBe(false);
  });
});

describe("멱등 키 유지", () => {
  it("불명확(0·504·500·503·코드 없는 502)은 같은 키 유지, 성공·4xx·확정 502(UPSTREAM_ERROR)는 새 키", async () => {
    const { retainKey } = await import("./ai-script");
    expect(retainKey("k", { ok: false, status: 0 })).toBe("k");
    expect(retainKey("k", { ok: false, status: 504 })).toBe("k");
    expect(retainKey("k", { ok: false, status: 500 })).toBe("k");
    expect(retainKey("k", { ok: false, status: 503 })).toBe("k");
    expect(retainKey("k", { ok: false, status: 502, code: "INTERNAL" })).toBe("k");
    expect(retainKey("k", { ok: false, status: 502 })).toBe("k");
    expect(retainKey("k", { ok: false, status: 502, code: "UPSTREAM_ERROR" })).toBeNull();
    expect(retainKey("k", { ok: false, status: 429 })).toBeNull();
    expect(retainKey("k", { ok: false, status: 409 })).toBeNull();
    expect(retainKey("k", { ok: true })).toBeNull();
  });
});

describe("applyVariant", () => {
  it("대본 4문장만 교체하고 나머지는 그대로", () => {
    const d = { ...emptyShoppingDraft(), cta: "링크 확인" };
    const next = applyVariant(d, ["가", "나", "다", "라"]);
    expect(next.script).toEqual(["가", "나", "다", "라"]);
    expect({ ...next, script: d.script }).toEqual(d);
  });
});
