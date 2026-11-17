import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const { UsedToggle, setCandidateUsed } = await import("./UsedToggle");

const ID = "00000000-0000-4000-8000-0000000000e1";

describe("setCandidateUsed", () => {
  const res = (status: number) => (async () => new Response("{}", { status })) as typeof fetch;

  it("상태코드 → 결과", async () => {
    expect(await setCandidateUsed(ID, true, res(200))).toBe("ok");
    expect(await setCandidateUsed(ID, true, res(401))).toBe("unauthorized");
    expect(await setCandidateUsed(ID, true, res(404))).toBe("not_found");
    expect(await setCandidateUsed(ID, true, res(400))).toBe("error");
    expect(await setCandidateUsed(ID, true, res(502))).toBe("error");
    const broken = (async () => {
      throw new TypeError("network");
    }) as typeof fetch;
    expect(await setCandidateUsed(ID, true, broken)).toBe("error");
  });

  it("PATCH + JSON 본문 {used}", async () => {
    let seen: [string, RequestInit | undefined] | null = null;
    const spy = (async (url: string, init?: RequestInit) => {
      seen = [url, init];
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await setCandidateUsed(ID, false, spy);
    expect(seen![0]).toBe(`/api/candidates/${ID}/used`);
    expect(seen![1]?.method).toBe("PATCH");
    expect(seen![1]?.body).toBe('{"used":false}');
  });
});

describe("UsedToggle", () => {
  it("상태에 따른 문구 + aria-live 영역", () => {
    expect(renderToStaticMarkup(<UsedToggle candidateId={ID} used={false} />)).toContain("사용함 표시");
    const html = renderToStaticMarkup(<UsedToggle candidateId={ID} used />);
    expect(html).toContain("표시 해제");
    expect(html).toContain('aria-live="polite"');
  });
});
