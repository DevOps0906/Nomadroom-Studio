import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const { DashboardError, DashboardHeader, DashboardSkeleton, DashboardSummaryView } = await import("./dashboard-view");
const { formatGrowth } = await import("./format");

type Summary = Parameters<typeof DashboardSummaryView>[0]["summary"];

const base: Summary = {
  stats: { collected: 13, in_progress: null, reviewed: null, upload_pending: null },
  stealth: { producible: 2, pending: 1 },
  recent_ready: [
    { id: "a", title: "<script>x</script> 영상", profile_name: null, growth_pct: 12.345, status_changed_at: "2026-11-16T00:30:00Z" },
  ],
  updated_at: "2026-11-17T01:00:00Z",
};

const count = (html: string, s: string) => html.split(s).length - 1;

describe("DashboardSummaryView", () => {
  it("성공: 수집 소재는 숫자, null 3칸은 —+운영 사이트 연동 전", () => {
    const html = renderToStaticMarkup(<DashboardSummaryView summary={base} />);
    expect(html).toContain(">13<");
    expect(count(html, "운영 사이트 연동 전")).toBe(3);
    expect(count(html, ">—<")).toBe(3 + 2); // 3칸 + 프로필 null(모바일 카드·표)
    expect(html).not.toContain("▲");
    expect(html).toContain("2건");
    expect(html).toContain("1건");
    expect(html).toContain('href="/monitor"');
  });

  it("후보 행: 제목 이스케이프·증가율·한국 시간", () => {
    const html = renderToStaticMarkup(<DashboardSummaryView summary={base} />);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("+12.3%");
    expect(html).toContain("09:30");
  });

  it("빈 데이터: 첫 사용 안내 + 소재수집(정체) 열기", () => {
    const empty: Summary = { ...base, stats: { ...base.stats, collected: 0 }, stealth: { producible: 0, pending: 0 }, recent_ready: [] };
    const html = renderToStaticMarkup(<DashboardSummaryView summary={empty} />);
    expect(html).toContain("아직 수집된 소재가 없습니다");
    expect(html).toContain("소재수집(정체) 열기");
    expect(html).not.toContain("<table");
  });

  it("기간 내 후보 없음: 표 대신 안내", () => {
    const html = renderToStaticMarkup(<DashboardSummaryView summary={{ ...base, recent_ready: [] }} />);
    expect(html).toContain("선택한 기간에 제작 가능 판정이 없습니다");
    expect(html).not.toContain("<table");
  });

  it("기간 안에만 데이터가 없으면 첫 사용 안내 대신 기간 안내(지표·정체 요약 유지)", () => {
    const quiet: Summary = { ...base, stats: { ...base.stats, collected: 0 }, recent_ready: [] };
    const html = renderToStaticMarkup(<DashboardSummaryView summary={quiet} />);
    expect(html).not.toContain("아직 수집된 소재가 없습니다");
    expect(html).toContain("이 기간에 새로 수집된 소재가 없습니다");
    expect(html).toContain("2건");
  });

  it("첫 사용 판정은 기간 무관 stealth 합을 본다: 근거 대기만 있어도 첫 사용 아님", () => {
    const html = renderToStaticMarkup(
      <DashboardSummaryView summary={{ ...base, stats: { ...base.stats, collected: 0 }, stealth: { producible: 0, pending: 1 }, recent_ready: [] }} />,
    );
    expect(html).not.toContain("아직 수집된 소재가 없습니다");
  });

  it("최근 후보: 모바일 카드(태블릿 이상 숨김) + 태블릿 이상 표(aria-labelledby)", () => {
    const html = renderToStaticMarkup(<DashboardSummaryView summary={base} />);
    expect(html).toMatch(/<ul aria-labelledby="dash-recent" class="[^"]*tablet:hidden/);
    expect(html).toMatch(/<div class="hidden [^"]*tablet:block"><table aria-labelledby="dash-recent"/);
    expect(html).toMatch(/<li[^>]*><p[^>]*>&lt;script&gt;x&lt;\/script&gt; 영상<\/p><p[^>]*>.*\+12\.3%.*09:30/);
  });

  it("지표 카드: 모바일 2열, 데스크톱 4열", () => {
    const html = renderToStaticMarkup(<DashboardSummaryView summary={base} />);
    expect(html).toContain('<dl class="grid grid-cols-2 gap-3 desktop:grid-cols-4">');
    expect(renderToStaticMarkup(<DashboardSkeleton />)).toContain("grid grid-cols-2 gap-3 desktop:grid-cols-4");
  });

  it("값이 있으면 연동 전 라벨을 붙이지 않는다", () => {
    const html = renderToStaticMarkup(
      <DashboardSummaryView summary={{ ...base, stats: { collected: 1, in_progress: 2, reviewed: 3, upload_pending: 4 } }} />,
    );
    expect(html).not.toContain("운영 사이트 연동 전");
  });
});

describe("로딩·오류·헤더", () => {
  it("로딩: 스켈레톤(status)", () => {
    const html = renderToStaticMarkup(<DashboardSkeleton />);
    expect(html).toContain('role="status"');
    expect(html).toContain("animate-pulse");
  });

  it("오류: 다시 시도 버튼 + 마지막 갱신 줄", () => {
    const html = renderToStaticMarkup(<DashboardError message="서버 응답이 늦습니다" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("다시 시도");
    expect(html).toContain("서버 응답이 늦습니다");
    expect(html).toContain("마지막 갱신");
  });

  it("헤더: 새 영상 만들기는 외부 새 탭, 선택 기간 표시", () => {
    const html = renderToStaticMarkup(<DashboardHeader period="24h" opsUrl="https://ops.example.com/" />);
    expect(html).toContain('href="https://ops.example.com/"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('target="_blank"');
    expect(html).toMatch(/aria-current="true"[^>]*>최근 24시간/);
  });

  it("헤더: 부제 문구, 쇼츠로 통일", () => {
    const html = renderToStaticMarkup(<DashboardHeader period="7d" opsUrl="" />);
    expect(html).toContain("소재 수집과 제작 가능 후보를 한눈에 확인하세요.");
    expect(html).toContain("쇼츠");
    expect(html).not.toContain("숏폼");
  });

  it("헤더: opsUrl이 비면 비활성", () => {
    const html = renderToStaticMarkup(<DashboardHeader period="7d" opsUrl="" />);
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain('target="_blank"');
  });

  it("formatGrowth", () => {
    expect([formatGrowth(null), formatGrowth(0), formatGrowth(-3.25)]).toEqual(["—", "0.0%", "-3.3%"]);
  });
});
