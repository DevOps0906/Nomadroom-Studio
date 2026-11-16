import { describe, expect, it, vi } from "vitest";
import { NavLink } from "./nav-link";

describe("NavLink 드로어 닫기", () => {
  it("외부 링크와 내부 링크 클릭 시 onNavigate를 부른다", () => {
    const onNavigate = vi.fn();
    const external = NavLink({ item: { key: "x", label: "주제 발굴", icon: "search" }, pathname: "/dashboard", opsUrl: "https://ops.example.com", onNavigate });
    const internal = NavLink({ item: { key: "d", label: "대시보드", href: "/dashboard", icon: "layout" }, pathname: "/dashboard", onNavigate });
    external?.props.onClick();
    internal?.props.onClick();
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });
});
