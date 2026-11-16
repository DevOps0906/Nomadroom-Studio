import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SidebarNav } from "./sidebar-nav";

describe("SidebarNav", () => {
  it("현재 경로에 aria-current를 달고 외부 링크는 새 탭으로 연다", () => {
    const html = renderToStaticMarkup(<SidebarNav pathname="/monitor" opsUrl="https://ops.example.com" />);
    const links = html.match(/<a [^>]*>/g) ?? [];
    const monitor = links.find((a) => a.includes('href="/monitor"'));
    const dash = links.find((a) => a.includes('href="/dashboard"'));
    expect(monitor).toContain('aria-current="page"');
    expect(dash).not.toContain("aria-current");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("운영 사이트 주소가 없으면 외부 링크를 비활성 표시한다", () => {
    const html = renderToStaticMarkup(<SidebarNav pathname="/dashboard" />);
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain('target="_blank"');
  });
});
