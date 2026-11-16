import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { LoginFormView } from "./login-form-view";
import { AUTH_ERROR_MESSAGES } from "./auth-messages";

const render = (props: Partial<Parameters<typeof LoginFormView>[0]> = {}) =>
  renderToStaticMarkup(<LoginFormView pending={false} error={null} email="" next="/" {...props} />);

describe("LoginFormView 상태", () => {
  it("기본: 입력 2개·로그인 버튼·링크 2개, 오류 없음", () => {
    const html = render();
    expect(html).toContain('name="email"');
    expect(html).toContain('name="password"');
    expect(html).toContain(">로그인</button>");
    expect(html).toContain('href="/forgot-password"');
    expect(html).toContain("이용약관·개인정보");
    expect(html).not.toContain('role="alert"');
    expect(html).not.toContain('disabled=""');
  });

  it("오류: 불일치 안내, 이메일 유지·비밀번호 비움", () => {
    const html = render({ error: "credentials", email: "op@example.com" });
    expect(html).toContain('role="alert"');
    expect(html).toContain(AUTH_ERROR_MESSAGES.credentials);
    expect(html).toContain('value="op@example.com"');
    expect(html).toMatch(/<input(?![^>]*value=)[^>]*name="password"[^>]*>/);
  });

  it("오류: 오류 문구 id를 입력칸 aria-describedby가 가리킨다", () => {
    const html = render({ error: "credentials" });
    expect(html).toContain('id="login-error"');
    expect(html.match(/aria-describedby="login-error"/g)).toHaveLength(2);
    expect(html.match(/aria-invalid="true"/g)).toHaveLength(2);
    expect(render()).not.toContain("aria-describedby");
  });

  it("429: 시도 제한 안내", () => {
    const html = render({ error: "rate_limited" });
    expect(html).toContain(AUTH_ERROR_MESSAGES.rate_limited);
  });

  it("로딩: 버튼 비활성 + 스피너", () => {
    const html = render({ pending: true });
    expect(html).toMatch(/<button[^>]*disabled=""/);
    expect(html).toContain('data-testid="spinner"');
    expect(html).toContain("로그인 중");
  });

  it("이메일 값은 이스케이프된다", () => {
    expect(render({ email: '"><script>' })).not.toContain("<script>");
  });
});
