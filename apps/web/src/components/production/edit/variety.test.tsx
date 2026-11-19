import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }) }));

const { EditForm } = await import("./edit-form");
const m = await import("./variety-model");
const { SourceForm } = await import("../source-form");

const JOB = { id: "00000000-0000-4000-8000-0000000000f1", title: "예능 작업", status: "review" as const, failed_stage: null, format: "variety" as const };
const spec = (over: Record<string, unknown> = {}) => ({
  lang: "ko",
  source_start_sec: 5,
  preset_version: "variety-1080-v1",
  header: { lines: ["첫째 줄", "둘째 줄"] },
  cuts: [
    { src_start: 0, src_end: 3, scale: 1.2, x: 0, y: 0 },
    { src_start: 4, src_end: 4.3, scale: 1, x: 10, y: -5 },
  ],
  subtitles: [{ start: 0, end: 1, style: "punch", text: "짧은 <b>대사</b>" }],
  reactions: [{ start: 0.5, end: 2, text: "헉", x: 540, y: 300 }],
  ...over,
});
const rev = (over: Record<string, unknown> = {}) => ({ rev_no: 2, spec: spec(), validation: { errors: [], warnings: [] }, approved_at: null, ...over });
const sheet = { jobId: JOB.id, sheetIds: ["s1"], sourceStart: 5, segmentLen: 30, sourceDuration: 120 };
const render = (revision: ReturnType<typeof rev> | null, job: typeof JOB | (Omit<typeof JOB, "status"> & { status: never }) = JOB) => renderToStaticMarkup(<EditForm job={job} revision={revision} sheet={sheet} />);

describe("예능형 편집 패널", () => {
  it("형식이 variety면 컷·자막·반응·제목 패널을 보이고 카테고리형 구도 행은 없다", () => {
    const html = render(rev());
    expect(html).toContain("예능형");
    expect(html).toContain("컷 (2/60)");
    expect(html).toContain("대사 1");
    expect(html).toContain("반응 1");
    expect(html).toContain("출력 총길이 3.3초");
    expect(html).toContain("0.5초 미만");
    expect(html).toContain("1.4초 미만");
    expect(html).toContain("punch(빨강)");
    expect(html).not.toContain("구도 행");
    expect(html).not.toContain("<b>대사</b>");
  });

  it("서버 검증 오류를 행에 표시하고 승인을 막고 사유 링크를 준다", () => {
    const html = render(
      rev({
        validation: {
          errors: [
            { code: "cuts.empty_area", path: "cuts.1", message: "띠가 덮이지 않습니다." },
            { code: "subtitles.overlap", path: "subtitles.0", message: "겹칩니다." },
          ],
          warnings: [{ code: "cuts.short", path: "cuts.1", message: "0.5초 미만" }],
        },
      }),
    );
    expect(html).toContain("검증 오류 2건");
    expect(html).toContain("빈 화면");
    expect(html).toContain("자막 겹침");
    expect(html).toMatch(/<button type="button" disabled=""[^>]*aria-describedby="approve-why"[^>]*>승인<\/button>/);
    expect(html).toContain('href="#edit-issues"');
  });

  it("오류 0·저장 완료면 승인 활성, 초안이 없으면 저장·승인 비활성과 안내", () => {
    expect(render(rev())).toMatch(/<button type="button" class="[^"]*">승인<\/button>/);
    const html = render(null);
    expect(html).toContain("컷이 없습니다");
    expect(html).toContain("원본 준비가 끝나면 편집안이 만들어집니다");
    expect(html).toMatch(/<button type="submit" disabled=""/);
  });

  it("승인됨·비편집 상태 사유를 보인다", () => {
    expect(render(rev({ approved_at: "2026-11-19T01:00:00Z" }))).toContain("이미 승인된 편집안");
    expect(render(rev(), { ...JOB, status: "rendering" as never })).toContain("현재 상태에서는 편집안을 고칠 수 없습니다.");
  });

  it("format이 없으면 카테고리형 폼을 쓴다", () => {
    const { format: _f, ...cat } = JOB;
    void _f;
    const html = renderToStaticMarkup(<EditForm job={cat} revision={null} sheet={sheet} />);
    expect(html).toContain("구도 행");
  });
});

describe("예능형 모델", () => {
  it("spec 왕복: 입력 변환은 읽기 전용 필드를 보존하고 둘째 제목 줄이 비면 1줄로 보낸다", () => {
    const d = m.toVarietyDraft(spec());
    const b = m.buildVarietySpec(d);
    expect(b.ok && b.spec).toMatchObject({ lang: "ko", source_start_sec: 5, preset_version: "variety-1080-v1", header: { lines: ["첫째 줄", "둘째 줄"] } });
    const one = m.buildVarietySpec({ ...d, header: ["하나", ""] });
    expect(one.ok && (one.spec.header as { lines: string[] }).lines).toEqual(["하나"]);
  });

  it("숫자가 아닌 칸은 위치와 함께 거부하고 순서 이동·누적 길이를 계산한다", () => {
    const d = m.toVarietyDraft(spec());
    d.cuts[1].x = "abc";
    expect(m.buildVarietySpec(d)).toMatchObject({ ok: false, path: "cuts.1.x" });
    expect(m.moveRow([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(m.moveRow([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
    expect(m.outputTotal(m.toVarietyDraft(spec()).cuts)).toBe(3.3);
  });

  it("타임라인: 대사 겹침은 bad, 반응 겹침은 warn", () => {
    const rows = [
      { start: "0", end: "2" },
      { start: "1", end: "3" },
    ];
    expect(m.timedSegments(rows, 5, true).every((s) => s.bad)).toBe(true);
    expect(m.timedSegments(rows, 5, false).every((s) => s.warn && !s.bad)).toBe(true);
  });
});

describe("예능형 AI 초안(task-040 A6)", () => {
  it("review면 AI 초안 버튼과 대사 전송 고지를 보인다", () => {
    const html = render(rev());
    expect(html).toMatch(/<button type="button"(?![^>]*disabled="")[^>]*>AI 초안 채우기<\/button>/);
    expect(html).toContain("AI 초안을 만들면 입력한 대사·분석 시트·후보 제목이 Anthropic(Claude)으로 전송됩니다.");
  });
  it("review가 아니면 AI 초안 버튼이 비활성이다", () => {
    const html = render(rev(), { ...JOB, status: "inspect" as never });
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>AI 초안 채우기<\/button>/);
  });
});

describe("PROD-01 형식 선택", () => {
  const src = (props: Record<string, unknown>) => renderToStaticMarkup(<SourceForm job={null} candidate={null} hasReadySource={false} {...props} />);
  it("새 작업은 형식을 고를 수 있고 initialFormat이 미리 선택된다", () => {
    const html = src({ initialFormat: "variety" });
    expect(html).toMatch(/<select id="src-format"(?![^>]*disabled="")[^>]*>/);
    expect(html).toMatch(/<option value="variety" selected=""/);
  });
  it("작업이 생긴 뒤에는 잠금과 사유를 보인다", () => {
    const job = { id: JOB.id, title: "t", status: "preparing" as const, failed_stage: null, error_code: null, rights_confirmed: true, license_cc: null, credit: null, source_start_sec: 0, segment_len_sec: 30, format: "variety" as const };
    const html = renderToStaticMarkup(<SourceForm job={job} candidate={null} hasReadySource={false} />);
    expect(html).toMatch(/<select id="src-format"[^>]*disabled=""/);
    expect(html).toContain("형식은 바꿀 수 없음");
  });
});
