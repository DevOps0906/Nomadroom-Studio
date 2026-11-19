import { describe, expect, it } from "vitest";
import * as m from "./model";

const file = (name: string, size = 10) => ({ name, size }) as File;

describe("금지 품목 1차 안내", () => {
  it.each(["건강기능식품 후기", "건 강 기능-식품", "ＳＵＰＰＬＥＭＥＮＴ 추천", "サプリ紹介", "의약품"])("우회·표기 차이도 잡는다: %s", (t) => {
    expect(m.findBanned(["무해한 제목", t])).not.toBeNull();
  });
  it("일반 문구는 통과", () => {
    expect(m.findBanned(["여름 텀블러", undefined, "보냉 12시간"])).toBeNull();
  });
});

describe("브리프 필수·전송 형태", () => {
  it("상품: 제품명·불편·장면 3~5", () => {
    const d = m.emptyBrief();
    expect(Object.keys(m.validateBrief("product", d)).sort()).toEqual(["pain", "product_name", "scenes"]);
    d.product_name = "텀블러";
    d.pain = "물이 미지근해짐";
    d.scenes = ["a", "b", "c"];
    expect(m.validateBrief("product", d)).toEqual({});
    d.scenes = ["a", "b", "c", "d", "e"];
    expect(m.validateBrief("product", d)).toEqual({});
    d.scenes = ["a", "b", " "];
    expect(m.validateBrief("product", d).scenes).toContain("현재 2개");
  });
  it("여행: 목적지·상품 종류·소구점", () => {
    const d = m.emptyBrief();
    d.scenes = ["a", "b", "c"];
    expect(Object.keys(m.validateBrief("travel", d)).sort()).toEqual(["appeal", "destination", "product_type"]);
  });
  it("전송 brief는 분야에 맞는 항목만(분야 외 항목은 서버 400)", () => {
    const d = { ...m.emptyBrief(), product_name: " 텀블러 ", destination: "제주", pain: "불편", appeal: "뷰", product_type: "stay" as const, scenes: ["a", "", "b", "c"], gender: "female" as const, age: "30대" };
    expect(m.briefPayload("product", d)).toEqual({ product_name: "텀블러", pain: "불편", scenes: ["a", "b", "c"], facts: [], target: { gender: "female", age: "30대" } });
    expect(m.briefPayload("travel", d)).toMatchObject({ destination: "제주", product_type: "stay", appeal: "뷰" });
    expect(m.briefPayload("travel", d)).not.toHaveProperty("product_name");
  });
});

describe("제휴 링크", () => {
  it("https만, 공백·사용자 정보 거부, 빈 행은 건너뜀", () => {
    const rows = [
      { lang: "ko" as const, partner: "쿠팡", url: "https://example.com/p?x=1" },
      { lang: "ko" as const, partner: "x", url: "http://example.com" },
      { lang: "ja" as const, partner: "y", url: "https://u:p@example.com" },
      { lang: "ja" as const, partner: "z", url: "https://exa mple.com" },
      { lang: "ko" as const, partner: "", url: "" },
      { lang: "ko" as const, partner: "", url: "https://example.com" },
    ];
    expect(Object.keys(m.validateAffiliates(rows)).map(Number)).toEqual([1, 2, 3, 5]);
    expect(m.affiliatesPayload(rows)).toHaveLength(5);
  });
});

describe("원본 행·권리", () => {
  it("영상은 source_upload, 사진은 image로 나눈다", () => {
    expect(m.classifyFile(file("a.MP4"))).toEqual({ kind: "source_upload", mime: "video/mp4" });
    expect(m.classifyFile(file("a.jpeg"))).toEqual({ kind: "image", mime: "image/jpeg" });
    expect(m.classifyFile(file("a.gif"))).toBeNull();
  });
  it("권리 근거 필수, 사진은 own·licensed만, 사람 등장이면 초상권 동의", () => {
    const base = { ...m.newRow(), file: file("a.jpg") };
    expect(m.validateRow(base).basis).toContain("선택");
    expect(m.validateRow({ ...base, basis: "permission" }).basis).toContain("직접 제작");
    expect(m.validateRow({ ...base, basis: "own" })).toEqual({});
    expect(m.validateRow({ ...base, basis: "own", has_person: true }).consent).toBeDefined();
    expect(m.validateRow({ ...base, basis: "own", has_person: true, portrait_consent: true })).toEqual({});
    expect(m.validateRow({ ...m.newRow(), basis: "own" }).file).toBeDefined();
    expect(m.validateRow({ ...m.newRow(), file: file("a.mp4"), basis: "quote" })).toEqual({});
  });
  it("전송 권리는 동의 없는 사람 등장 값을 만들지 않는다", () => {
    expect(m.rightsOf({ ...m.newRow(), basis: "own", has_person: false, portrait_consent: true })).toEqual({ basis: "own", has_person: false, portrait_consent: false });
  });
  it("경고: 원본 3개 미만(막지 않음)·금지·초상권", () => {
    const ids = (w: m.SourceWarning[]) => w.map((x) => x.id);
    expect(ids(m.sourceWarnings({ sources: 2, banned: null, consentMissing: false, hasVideo: true }))).toEqual(["few"]);
    expect(ids(m.sourceWarnings({ sources: 3, banned: null, consentMissing: false, hasVideo: true }))).toEqual([]);
    expect(ids(m.sourceWarnings({ sources: 3, banned: "영양제", consentMissing: true, hasVideo: false }))).toEqual(["banned", "consent", "video"]);
  });
  it("편집은 draft·준비 실패만", () => {
    expect(m.isSourceEditable("draft", null)).toBe(true);
    expect(m.isSourceEditable("failed", "prepare")).toBe(true);
    expect(m.isSourceEditable("preparing", null)).toBe(false);
    expect(m.isSourceEditable("review", null)).toBe(false);
  });
});

describe("대본 카운터·타임라인", () => {
  it("글자 수 합계·범위·금지 문구·[확인 필요]", () => {
    const ok = ["가".repeat(30), "나".repeat(30), "다".repeat(30), "라".repeat(30)];
    expect(m.scriptHints(ok)).toMatchObject({ total: 120, outOfRange: false, banned: {}, marked: [] });
    const bad = ["짧음", "인생 템이에요", `${m.CONFIRM_MARK} 확인`, ""];
    const h = m.scriptHints(bad);
    expect(h.outOfRange).toBe(true);
    expect(h.banned).toEqual({ 1: "인생템" });
    expect(h.marked).toEqual([2]);
    expect(m.charCount("😀a")).toBe(2);
  });
  it("문장별 컷 길이와 빈 문장", () => {
    const d = m.emptyShoppingDraft();
    d.cuts = [
      { source_asset_id: "a", src_start: "0", src_end: "2", scale: "1", x: "0", y: "0", sentence: "1", masks: [], motion: "zoom" },
      { source_asset_id: "a", src_start: "2", src_end: "5", scale: "1", x: "0", y: "0", sentence: "1", masks: [], motion: "zoom" },
      { source_asset_id: "b", src_start: "0", src_end: "3", scale: "1", x: "0", y: "0", sentence: "3", masks: [], motion: "zoom" },
    ];
    d.mode = "narration";
    d.narrationIds = ["n1", null, null, null];
    const segs = m.sentenceSegments(d, (id) => (id === "n1" ? 4.2 : null));
    expect(segs.map((s) => [s.seconds, s.cuts, s.empty])).toEqual([[5, 2, false], [0, 0, true], [3, 1, false], [0, 0, true]]);
    expect(segs[0]!.voiceSec).toBe(4.2);
  });
});

describe("편집안 spec 변환", () => {
  const spec = {
    lang: "ko",
    preset_version: "shopping-1080-v1",
    script: [{ text: "하나" }, { text: "둘" }, { text: "셋" }, { text: "넷" }],
    cuts: [
      { source_asset_id: "img1", src_start: 0, src_end: 3, scale: 1, x: 0, y: 0, sentence: 1, masks: [{ x: 0, y: 10, w: 100, h: 50 }], motion: { type: "pan" } },
      { source_asset_id: "vid1", src_start: 1, src_end: 4, scale: 1.5, x: 5, y: -5, sentence: 2, masks: [] },
    ],
    voice: { narration_asset_ids: ["n1", "n2", "n3", "n4"] },
    source_audio: "duck",
    bgm_asset_id: "b1",
    cta: { text: "링크 확인" },
    disclosure: { text: "아무 문구" },
  };
  it("읽고 쓰면 같은 구조이고 표기 문구는 고정값이다", () => {
    const d = m.toShoppingDraft(spec);
    expect(d.mode).toBe("narration");
    expect(d.narrationIds).toEqual(["n1", "n2", "n3", "n4"]);
    expect(d.cuts[0]!.motion).toBe("pan");
    const r = m.buildShoppingSpec(d, new Set(["img1"]));
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.spec.disclosure).toEqual({ text: "제휴 링크 포함" });
    expect(r.spec.voice).toEqual({ narration_asset_ids: ["n1", "n2", "n3", "n4"] });
    const cuts = r.spec.cuts as Record<string, unknown>[];
    expect(cuts[0]!.motion).toEqual({ type: "pan" });
    expect(cuts[1]).not.toHaveProperty("motion"); // 영상 컷에는 motion 없음
    expect(r.spec.preset_version).toBe("shopping-1080-v1"); // 읽기 전용 값은 그대로 통과
  });
  it("숫자가 아닌 칸·잘못된 TTS는 보내지 않고 위치를 돌려준다", () => {
    const d = m.toShoppingDraft(spec);
    d.cuts[1]!.src_end = "abc";
    expect(m.buildShoppingSpec(d, new Set())).toMatchObject({ ok: false, path: "cuts.1.src_end" });
    const t = { ...m.emptyShoppingDraft(), tts: { voice: "bad", rate: "+0%" } };
    expect(m.buildShoppingSpec(t, new Set())).toMatchObject({ ok: false, path: "voice.tts.voice" });
    const u = { ...m.emptyShoppingDraft(), tts: { voice: "ko-KR-SunHiNeural", rate: "fast" } };
    expect(m.buildShoppingSpec(u, new Set())).toMatchObject({ ok: false, path: "voice.tts.rate" });
  });
  it("표기 문구는 rest.lang으로 고른다(ko 제휴 링크 포함 · ja PR)", () => {
    const build = (lang?: string) => {
      const r = m.buildShoppingSpec({ ...m.emptyShoppingDraft(), rest: lang ? { lang } : {} }, new Set());
      return r.ok ? r.spec.disclosure : null;
    };
    expect(build("ko")).toEqual({ text: "제휴 링크 포함" });
    expect(build("ja")).toEqual({ text: "PR" });
    expect(build()).toEqual({ text: "제휴 링크 포함" });
    expect(m.DISCLOSURE_TEXT).toEqual({ ko: "제휴 링크 포함", ja: "PR" });
  });
  it("업로드 성공 뒤 준비 시작이 실패해 재시도해도 원본 수에 이미 올린 자산이 남는다", () => {
    // 새 작업: 서버 목록(props)은 비어 있고 행은 업로드되며 빠졌다. 재시도에서 "원본 1개 이상" 오류가 나면 안 된다.
    expect(m.countSources([], [], [])).toEqual({ count: 0, hasVideo: false });
    expect(m.countSources([], [], ["source_upload", "image"])).toEqual({ count: 2, hasVideo: true });
    const row = { ...m.newRow(), file: file("b.jpg") };
    expect(m.countSources([{ kind: "source_upload" }], [row], ["image"])).toEqual({ count: 3, hasVideo: true });
    expect(m.countSources([], [row], [])).toEqual({ count: 1, hasVideo: false });
  });
  it("빈 초안은 문장 4개를 만든다", () => {
    expect(m.toShoppingDraft({}).script).toHaveLength(4);
    expect(m.shoppingIssueLabel({ code: "cuts.sentence_empty", path: "cuts", message: "x" })).toBe("문장에 컷 없음");
  });
});
