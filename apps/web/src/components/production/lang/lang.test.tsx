import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

// task-052 언어 탭: 탭 상태·잠금 필드·source_changed 안내·번역 경로·리포트 경고(순수 함수 + 정적 렌더).

vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => {} }) }));

const m = await import("./model");
const { LangTabs } = await import("./lang-tabs");
const { JaPanel } = await import("./ja-panel");
const { JaRunView } = await import("./ja-run");
const { jaRunState } = await import("./run-model");

const CATEGORY = {
  lang: "ja",
  header: { lines: ["一行目", "二行目"] },
  hook: { text: "フック", tts: { voice: "ja-JP-NanamiNeural" } },
  shots: [{ start: 0, end: 5, scale: 1, y: 0 }],
  items: [{ start: 0, end: 2, kind: "white", text: "字幕1" }],
  overlays: [{ kind: "comment", text: "コメント", start: 0, end: 2, x: 1, y: 2 }],
};
const SHOPPING = { script: [{ text: "一" }, { text: "二" }, { text: "三" }, { text: "四" }], cta: { text: "リンク" }, disclosure: { text: "PR" }, cuts: [{ sentence: 1 }] };
const VARIETY = { header: { lines: ["題"] }, subtitles: [{ text: "台詞", style: "line" }], reactions: [{ text: "反応" }], cuts: [] };

describe("탭 상태", () => {
  it("lang 쿼리 해석·링크", () => {
    expect(m.parseLang("ja")).toBe("ja");
    expect(m.parseLang(["ja", "ko"])).toBe("ja");
    expect(m.parseLang("en")).toBe("ko");
    expect(m.parseLang(undefined)).toBe("ko");
    expect(m.langHref("/production/1/edit", "ja")).toBe("/production/1/edit?lang=ja");
    expect(m.langHref("/production/1/edit", "ko")).toBe("/production/1/edit");
  });
  it("활성 탭은 aria-current, ja 없음 표시", () => {
    const html = renderToStaticMarkup(<LangTabs basePath="/production/1/edit" active="ja" jaExists={false} />);
    expect(html).toContain("?lang=ja");
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
    expect(html).toContain("(없음)");
    expect(renderToStaticMarkup(<LangTabs basePath="/p" active="ko" jaExists />)).not.toContain("(없음)");
  });
  it("ko 미승인이면 일본어판 만들기 비활성(사유)", () => {
    expect(m.makeGate(null).enabled).toBe(false);
    expect(m.makeGate({ approved_at: null }).enabled).toBe(false);
    expect(m.makeGate({ approved_at: "x" })).toEqual({ enabled: true, reason: null });
    const html = renderToStaticMarkup(<JaPanel job={{ id: "j", format: "category" }} ko={{ id: "k", rev_no: 1, approved_at: null }} ja={null} />);
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>일본어판 만들기/);
    expect(html).toContain("승인되기 전에는");
    expect(html).toContain("외부 AI(Claude)로 전송");
  });
});

describe("번역 경로·잠금 필드", () => {
  it("형식별 번역 대상 문구만 뽑는다", () => {
    expect(m.extractTexts("category", CATEGORY).map((f) => f.key)).toEqual(["header.lines.0", "header.lines.1", "hook.text", "items.0.text", "overlays.0.text"]);
    expect(m.extractTexts("variety", VARIETY).map((f) => f.key)).toEqual(["header.lines.0", "subtitles.0.text", "reactions.0.text"]);
    expect(m.extractTexts("shopping", SHOPPING).map((f) => f.key)).toEqual(["script.0.text", "script.1.text", "script.2.text", "script.3.text", "cta.text"]);
  });
  it("수정은 문구만 바꾸고 나머지 필드(구도·음성·표기)는 그대로", () => {
    const next = m.applyTexts("category", CATEGORY, { "hook.text": "新フック", "items.0.text": "新字幕" });
    expect((next.hook as { text: string }).text).toBe("新フック");
    expect((next.items as { text: string }[])[0].text).toBe("新字幕");
    expect(next.shots).toEqual(CATEGORY.shots);
    expect((next.hook as { tts: unknown }).tts).toEqual(CATEGORY.hook.tts);
    expect(CATEGORY.hook.text).toBe("フック");
    const s = m.applyTexts("shopping", SHOPPING, { "cta.text": "新" });
    expect(s.disclosure).toEqual(SHOPPING.disclosure);
    expect(s.cuts).toEqual(SHOPPING.cuts);
  });
  it("변경 감지", () => {
    expect(m.isDirty("category", CATEGORY, m.textsOf("category", CATEGORY))).toBe(false);
    expect(m.isDirty("category", CATEGORY, { "hook.text": "x" })).toBe(true);
  });
  it("ja 리비전 화면: 문구 입력·잠금 안내·음성 안내, 구도 입력은 없음", () => {
    const ja = { id: "j", rev_no: 1, spec: CATEGORY, origin: "ai_draft" as const, validation: { errors: [], warnings: [] }, approved_at: null, updated_at: "t" };
    const html = renderToStaticMarkup(<JaPanel job={{ id: "j", format: "category" }} ko={{ id: "k", rev_no: 1, approved_at: "x" }} ja={ja} />);
    expect(html).toContain("잠금 필드");
    expect(html).toContain(m.LOCKED_NOTE.category);
    expect(html).toContain(m.VOICE_NOTE);
    expect(html).toContain('value="フック"');
    expect(html).not.toContain('id="ja-shots');
    expect(html.match(/<input /g)).toHaveLength(5);
    expect(html).toContain("번역 초안");
    expect(html).not.toContain("다시 만들기");
  });
});

describe("원본 변경 안내", () => {
  const issue = { code: "ja.source_changed", path: "", message: "원본 변경" };
  it("source_changed면 다시 만들기·안내, 승인 차단", () => {
    expect(m.hasSourceChanged([issue])).toBe(true);
    expect(m.approveBlockers({ dirty: false, saving: false, approved: false, errors: [issue] }).join()).toContain("다시 만들기");
    expect(m.approveBlockers({ dirty: false, saving: false, approved: false, errors: [] })).toEqual([]);
    const ja = { id: "j", rev_no: 1, spec: CATEGORY, origin: "user" as const, validation: { errors: [issue], warnings: [] }, approved_at: null, updated_at: "t" };
    const html = renderToStaticMarkup(<JaPanel job={{ id: "j", format: "category" }} ko={{ id: "k", rev_no: 2, approved_at: "x" }} ja={ja} />);
    expect(html).toContain("다시 만들기");
    expect(html).toContain("보관됩니다");
  });
});

describe("PROD-03 ja 탭", () => {
  it("ja 상태별 안내·렌더 요청 가능 여부", () => {
    expect(jaRunState(null).canRequest).toBe(false);
    expect(jaRunState({ approved_at: null }).canRequest).toBe(false);
    expect(jaRunState({ approved_at: "x" }).canRequest).toBe(true);
  });
  it("승인된 ja는 렌더 요청 버튼(예능형도 막지 않음), 없으면 일본어판 만들기 안내", () => {
    const ok = renderToStaticMarkup(<JaRunView job={{ id: "j", shopping: false }} ja={{ id: "r", rev_no: 1, approved_at: "x" }} reportId={null} />);
    expect(ok).toContain("렌더 요청");
    expect(ok).not.toContain("준비 중");
    const none = renderToStaticMarkup(<JaRunView job={{ id: "j", shopping: false }} ja={null} reportId={null} />);
    expect(none).toContain("일본어판 만들기(편집안으로)");
    expect(none).toContain("/edit?lang=ja");
  });
});

describe("리포트 경고", () => {
  it("dub_overflow는 대사 번호·초과 초, dub_none은 대사 없음", () => {
    expect(m.warningText({ code: "dub_overflow", line: 3, overflow_sec: 0.4 })).toContain("대사 3번");
    expect(m.warningText({ code: "dub_overflow", line: 3, overflow_sec: 0.4 })).toContain("0.40초");
    expect(m.warningText({ code: "dub_none" })).toContain("대사 자막이 없어");
    expect(m.warningText({ code: "x.y" })).toBe("x.y");
  });
  it("리포트 언어가 탭과 다르면 숨김, 모르면 표시", () => {
    const w = [{ code: "dub_none" }];
    expect(m.warningsForLang({ lang: "ja", warnings: w }, "ko")).toEqual([]);
    expect(m.warningsForLang({ lang: "ja", warnings: w }, "ja")).toEqual(w);
    expect(m.warningsForLang({ lang: null, warnings: w }, "ko")).toEqual(w);
  });
});

describe("탭 전환 확인·대사 순번·고지", () => {
  it("미저장이면 확인 후에만 이동, 취소하면 이동 안 함", async () => {
    const g = await import("./dirty-guard");
    g.setLangDirty(false);
    expect(g.confirmLangLeave(() => false)).toBe(true);
    g.setLangDirty(true);
    expect(g.confirmLangLeave(() => false)).toBe(false);
    expect(g.confirmLangLeave(() => true)).toBe(true);
    g.setLangDirty(false);
  });
  it("대사 순번은 style=line만 start순 1부터(강조 제외)", () => {
    const subs = [
      { style: "line", start: "5" },
      { style: "punch", start: "1" },
      { style: "line", start: "2" },
    ];
    expect(m.dubOrdinals(subs)).toEqual([2, null, 1]);
    expect(m.warningText({ code: "dub_overflow", line: 2, overflow_sec: 0.1 })).toContain("강조 제외 순번");
  });
  it("ja 렌더 요청 근처에 TTS 외부 전송 고지", () => {
    const html = renderToStaticMarkup(<JaRunView job={{ id: "j", shopping: false }} ja={{ id: "r", rev_no: 1, approved_at: "x" }} reportId={null} />);
    expect(html).toContain("외부 음성 합성(TTS) 서비스로 전송됩니다");
    expect(renderToStaticMarkup(<JaRunView job={{ id: "j", shopping: false }} ja={null} reportId={null} />)).not.toContain("음성 합성");
  });
});

describe("task-059 저장 잠금(ja)", () => {
  const AT = "2026-11-02T00:00:00.123456Z";
  it("반환 updated_at으로 연속 저장 2회 성공, 낡은 base·승인본 낡은 base는 409", async () => {
    const { saveJaRevision } = await import("./api");
    const { lockServer } = await import("../lock-server.test-util");
    const srv = lockServer({ rev_no: 1, updated_at: AT, approved: false });
    const r1 = await saveJaRevision("j", {}, 1, AT, srv.f);
    if (!r1.ok) throw new Error("r1");
    expect((await saveJaRevision("j", {}, 1, r1.data.revision.updated_at, srv.f)).ok).toBe(true);
    expect(await saveJaRevision("j", {}, 1, AT, srv.f)).toMatchObject({ ok: false, status: 409 });
    const approved = lockServer({ rev_no: 1, updated_at: AT, approved: true });
    expect(await saveJaRevision("j", {}, 1, "2000-01-01T00:00:00Z", approved.f)).toMatchObject({ ok: false, status: 409 });
  });
  it("저장 → applySaved 상태로 이어서 입력·저장 연속 성공(새로고침 없음)", async () => {
    const { saveJaRevision } = await import("./api");
    const { lockServer } = await import("../lock-server.test-util");
    const srv = lockServer({ rev_no: 1, updated_at: AT, approved: false });
    let rev = { id: "j", rev_no: 1, spec: CATEGORY, origin: "ai_draft" as const, validation: { errors: [], warnings: [] }, approved_at: null, updated_at: AT };
    for (const text of ["一回目", "二回目", "三回目"]) {
      const spec = m.applyTexts("category", rev.spec, { ...m.textsOf("category", rev.spec), "hook.text": text });
      const r = await saveJaRevision("j", spec, rev.rev_no, rev.updated_at, srv.f);
      if (!r.ok) throw new Error(`save ${text}: ${r.status}`);
      rev = m.applySaved(rev, spec, r.data.revision) as typeof rev;
      expect(m.isDirty("category", rev.spec, m.textsOf("category", spec))).toBe(false);
    }
    expect(rev.updated_at).toBe(srv.state.updated_at);
    expect(rev.origin).toBe("user");
  });
  it("409 안내 문구", async () => {
    const { SAVE_CONFLICT } = await import("./ja-panel");
    expect(SAVE_CONFLICT).toContain("다른 곳에서 먼저 수정");
    expect(SAVE_CONFLICT).toContain("새로고침");
  });
});
