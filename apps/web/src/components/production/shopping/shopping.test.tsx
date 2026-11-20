import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProductionAsset } from "@/server/api/production";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { ShoppingSourceForm } = await import("./source-form");
const { ShoppingEditForm } = await import("./edit-form");
const { PublishTextView, RightsList, copyText } = await import("../run/shopping-extras");
const { chooserHref } = await import("../type-chooser");
const { formatText } = await import("../job-list-view");
const api = await import("./api");

const JOB_ID = "00000000-0000-4000-8000-0000000000a1";
const sourceJob = (over: Record<string, unknown> = {}) => ({
  id: JOB_ID,
  title: "텀블러 쇼츠",
  status: "draft" as const,
  failed_stage: null,
  error_code: null,
  vertical: "product" as const,
  brief: { product_name: "텀블러", pain: "미지근해짐", scenes: ["a", "b", "c"], facts: ["12시간 보냉"] },
  affiliates: [{ lang: "ko" as const, partner: "쿠팡", url: "https://example.com/p" }],
  comment_keyword: "텀블러",
  ...over,
});
const assets = [
  { id: "a1", kind: "source_upload", status: "ready" as const, size_bytes: 1048576 },
  { id: "a2", kind: "image", status: "ready" as const, size_bytes: 2048 },
];

describe("유형 선택(PROD-00 제작 시작)", () => {
  it("선택이 끝나야 계속 주소가 생긴다", () => {
    expect(chooserHref(null, null)).toBeNull();
    expect(chooserHref("general", null)).toBeNull();
    expect(chooserHref("general", "variety")).toBe("/production/new?kind=general&format=variety");
    expect(chooserHref("shopping", "category")).toBeNull();
    expect(chooserHref("shopping", "travel")).toBe("/production/new?kind=shopping&vertical=travel");
  });
  it("목록 형식 칸은 쇼핑이면 분야까지", () => {
    expect(formatText({ format: "shopping", kind: "shopping", vertical: "product" })).toBe("쇼핑·상품");
    expect(formatText({ format: "variety", vertical: null })).toBe("예능형");
  });
});

describe("PROD-01S 원본·브리프", () => {
  it("새 작업: 분야 선택·금지 품목 확인·원본 행·제휴 링크·준비 시작이 있다", () => {
    const html = renderToStaticMarkup(<ShoppingSourceForm job={null} assets={[]} initialVertical="travel" />);
    expect(html).toContain("금지 품목 아님 확인");
    expect(html).toContain("원본 (0/10)");
    expect(html).toContain("새 원본 1");
    expect(html).toContain("권리 근거");
    expect(html).toContain("목적지");
    expect(html).toContain("상품 종류");
    expect(html).toContain("소구점 1개");
    expect(html).toContain("실제 장면 3~5개");
    expect(html).toContain("제휴 링크 (0/20)");
    expect(html).toContain("원본이 3개 미만입니다");
    expect(html).toContain("원본 준비 시작");
    expect(html).not.toContain("제품명");
  });
  it("상품 분야는 제품명·불편 1개·빼야 할 말을 보인다", () => {
    const html = renderToStaticMarkup(<ShoppingSourceForm job={null} assets={[]} initialVertical="product" />);
    expect(html).toContain("제품명");
    expect(html).toContain("해결하는 불편 1개");
    expect(html).toContain("빼야 할 말");
    expect(html).not.toContain("목적지");
  });
  it("저장된 작업: 올라간 원본 삭제 버튼·분야 읽기 전용(준비 후)·제목 잠금", () => {
    const draft = renderToStaticMarkup(<ShoppingSourceForm job={sourceJob()} assets={assets} />);
    expect(draft).toContain("원본 1 · 영상");
    expect(draft).toContain("원본 2 · 사진");
    expect(draft).toContain('aria-label="원본 1 삭제"');
    expect(draft).toContain("제목은 생성 후 바꿀 수 없습니다");
    expect(draft).toContain("텀블러 쇼츠");
    const prep = renderToStaticMarkup(<ShoppingSourceForm job={sourceJob({ status: "preparing" })} assets={assets} />);
    expect(prep).toContain("분야는 바꿀 수 없음");
    expect(prep).toContain("원본 준비 중");
    expect(prep).toMatch(/<select id="sh-vertical"[^>]*disabled/);
  });
  it("준비 완료면 편집안으로 링크가 켜진다", () => {
    const html = renderToStaticMarkup(<ShoppingSourceForm job={sourceJob({ status: "review" })} assets={assets} />);
    expect(html).toContain(`href="/production/${JOB_ID}/edit"`);
  });
  it("금지 키워드가 있으면 경고(막는 안내)가 보인다", () => {
    const html = renderToStaticMarkup(<ShoppingSourceForm job={sourceJob({ brief: { product_name: "비타민 영양제", scenes: [] } })} assets={assets} />);
    expect(html).toContain("금지 품목 키워드가 있습니다(영양제)");
  });
});

const spec = {
  lang: "ko",
  script: [{ text: "가".repeat(30) }, { text: "나".repeat(30) }, { text: "다 [확인 필요]" }, { text: "라".repeat(30) }],
  cuts: [
    { source_asset_id: "a1", src_start: 0, src_end: 3, scale: 1, x: 0, y: 0, sentence: 1, masks: [{ x: 0, y: 0, w: 10, h: 10 }] },
    { source_asset_id: "a2", src_start: 0, src_end: 2, scale: 1, x: 0, y: 0, sentence: 2, masks: [], motion: { type: "zoom" } },
  ],
  voice: { narration_asset_ids: ["n1", "n2", "n3", "n4"] },
  cta: { text: "링크 확인" },
  disclosure: { text: "제휴 링크 포함" },
};
const rev = (over: Record<string, unknown> = {}) => ({ rev_no: 2, spec, validation: { errors: [], warnings: [] }, approved_at: null, updated_at: "2026-11-02T00:00:00.123456Z", ...over });
const editAssets = [
  { id: "a1", kind: "source_upload", status: "ready" as const, duration_sec: 20 },
  { id: "a2", kind: "image", status: "ready" as const, duration_sec: null },
  ...["n1", "n2", "n3", "n4"].map((id) => ({ id, kind: "narration", status: "ready" as const, duration_sec: 3 })),
];
const editJob = { id: JOB_ID, title: "텀블러 쇼츠", status: "review" as const, failed_stage: null, vertical: "product" as const };
const sheet = { jobId: JOB_ID, sheetIds: ["s1"], sourceStart: 0, segmentLen: 30, sourceDuration: 20 };
const renderEdit = (revision: ReturnType<typeof rev> | null, job = editJob) =>
  renderToStaticMarkup(<ShoppingEditForm job={job} revision={revision} sheet={sheet} brief={{ product_name: "텀블러", facts: ["12시간 보냉"] }} assets={editAssets} />);

describe("PROD-02S 편집안", () => {
  it("4문장 카운터·합계·확인 필요 배지·브리프 요약", () => {
    const html = renderEdit(rev());
    expect(html).toContain("대본 4문장");
    expect(html).toMatch(/합계 (<!-- -->)?99(<!-- -->)?자/);
    expect(html).toContain("글자 수가 권장 범위를 벗어났습니다");
    expect(html).toContain("1번 문장 글자 수");
    expect(html).toContain("[확인 필요]");
    expect(html).toContain("브리프 요약");
    expect(html).toContain("12시간 보냉");
  });
  it("문장별 컷·원본 선택·마스크·사진 모션·시트·타임라인", () => {
    const html = renderEdit(rev());
    expect(html).toContain("컷 (2)");
    expect(html).toContain("영상 원본 1");
    expect(html).toContain("사진 1");
    expect(html).toContain("마스크 (1)");
    expect(html).toContain("zoom(기본)");
    expect(html).toContain("시트 1 보기");
    expect(html).toContain("3번 문장: 컷 없음");
    expect(html).toContain("컷 1 위로");
  });
  it("녹음 4개(문장별)와 고정 표기 문구", () => {
    const html = renderEdit(rev());
    expect(html).toContain("녹음 4/4");
    for (const n of [1, 2, 3, 4]) expect(html).toContain(`${n}번 문장 녹음`);
    expect(html).toContain('value="제휴 링크 포함"');
    expect(html).toContain("링크 확인");
  });
  it("서버 오류는 행에 표시하고 승인을 막고 사유 링크를 준다", () => {
    const html = renderEdit(rev({ validation: { errors: [{ code: "cuts.sentence_empty", path: "cuts", message: "3번 문장에 컷이 없습니다." }], warnings: [{ code: "sources.few", path: "cuts", message: "사용 원본이 3개 미만입니다." }] } }));
    expect(html).toContain("검증 오류 1건");
    expect(html).toContain("문장에 컷 없음");
    expect(html).toContain("원본 3개 미만");
    expect(html).toMatch(/<button type="button" disabled=""[^>]*aria-describedby="approve-why"[^>]*>승인<\/button>/);
    expect(html).toContain('href="#edit-issues"');
  });
  it("초안이 없으면 안내하고 저장을 막는다", () => {
    const html = renderEdit(null);
    expect(html).toContain("편집안 초안이 아직 없습니다");
    expect(html).toMatch(/<button type="submit" disabled=""/);
  });
});

describe("PROD-03 게시 문구·권리 목록", () => {
  const text = { caption: "제휴 링크 포함\n텀블러 보기", pinned_comment: "https://example.com/p", recommended_time: "오전 8시" };
  it("세 항목과 항목별 복사 버튼", () => {
    const html = renderToStaticMarkup(<PublishTextView text={text} onCopy={() => {}} />);
    expect(html).toContain("설명란");
    expect(html).toContain("고정 댓글");
    expect(html).toContain("업로드 권장 시각 메모");
    expect(html.match(/>복사</g)).toHaveLength(3);
    expect(html).toContain("제휴 링크 포함");
  });
  it("복사는 클립보드로 보내고 실패하면 false", async () => {
    const writeText = vi.fn(async () => {});
    expect(await copyText("abc", { writeText })).toBe(true);
    expect(writeText).toHaveBeenCalledWith("abc");
    expect(await copyText("abc", { writeText: async () => Promise.reject(new Error("denied")) })).toBe(false);
    expect(await copyText("abc", undefined)).toBe(false);
  });
  const asset = (over: Partial<ProductionAsset>): ProductionAsset => ({ id: "x", kind: "image", status: "ready", size_bytes: 2048, duration_sec: null, ...over });
  it("권리 목록: 근거·출처·저작자·사람 등장·초상권 동의(응답에 있을 때)", () => {
    const html = renderToStaticMarkup(
      <RightsList assets={[asset({ rights: { basis: "licensed", source_url: "https://example.com/s", author: "홍길동", has_person: true, portrait_consent: true } }), asset({ id: "y", kind: "output_mp4" })]} />,
    );
    expect(html).toContain("사진 1");
    expect(html).toContain("라이선스");
    expect(html).toContain("홍길동");
    expect(html).toContain("동의");
    expect(html).not.toContain("output_mp4");
    expect(html).not.toContain("권리 정보가 아직 입력되지 않았습니다");
  });
  it("권리 값이 응답에 없으면 그 사실을 알린다", () => {
    expect(renderToStaticMarkup(<RightsList assets={[asset({})]} />)).toContain("권리 정보가 아직 입력되지 않았습니다");
    expect(renderToStaticMarkup(<RightsList assets={[]} />)).toContain("올린 자산이 없습니다");
  });
});

describe("쇼핑 브라우저 호출", () => {
  const calls: { url: string; method: string; body: unknown }[] = [];
  const f = (async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET", body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
    if (String(url).includes("/uploads") && init?.method === "POST" && !String(url).includes("complete"))
      return new Response(JSON.stringify({ asset: { id: "as1" }, upload_url: ["https://s", "/u"].join(""), expires_at: "x" }), { status: 200 });
    return new Response(JSON.stringify({ ok: true, asset: { id: "as1", status: "ready" } }), { status: 200 });
  }) as unknown as typeof fetch;

  it("쇼핑 생성은 kind·format·분야·금지 품목 확인을 보낸다(작업 단위 권리는 false)", async () => {
    calls.length = 0;
    await api.createShoppingJob("제목", { vertical: "product", brief: { product_name: "a" } }, ["key-", "12345678"].join(""), f);
    expect(calls[0]!.body).toMatchObject({ kind: "shopping", format: "shopping", vertical: "product", not_banned_confirmed: true, rights_confirmed: false, source_kind: "upload" });
  });
  it("자산 업로드: 서명 요청(권리 포함) → PUT → 완료 확인", async () => {
    calls.length = 0;
    const r = await api.uploadAsset(JOB_ID, { size: 5, name: "a.jpg" } as File, "image", "image/jpeg", { basis: "own" }, f);
    expect(r).toEqual({ ok: true, data: { assetId: "as1" } });
    expect(calls.map((c) => c.method + " " + c.url.split("/").slice(-1)[0])).toEqual(["POST uploads", "PUT u", "POST complete"]);
    expect(calls[0]!.body).toMatchObject({ kind: "image", rights: { basis: "own" } });
  });
  it("자산 삭제는 DELETE, 게시 문구는 POST", async () => {
    calls.length = 0;
    await api.deleteAsset(JOB_ID, "as1", f);
    await api.fetchPublishText(JOB_ID, "ko", f);
    expect(calls.map((c) => c.method)).toEqual(["DELETE", "POST"]);
    expect(calls[1]!.url).toContain("/publish-text");
  });
});
