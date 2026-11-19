import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), replace: vi.fn() }) }));

const { EmptyJobs, JobTable, JobsError, JobsSkeleton, NoFilterResult, StatusFilter, jobHref } = await import("./job-list-view");
const { SourceForm, isEditable } = await import("./source-form");
const { CandidateCard } = await import("./source-view");
const { candidateHref, validateSource, mimeOf, parseStatus } = await import("./format");
const { createJob, putFile } = await import("./api");

const ID = "00000000-0000-4000-8000-0000000000e1";
const item = (over: Record<string, unknown> = {}) => ({
  id: ID,
  title: "제목 <b>x</b>",
  format: "category" as const,
  status: "draft" as const,
  failed_stage: null,
  error_code: null,
  candidate_id: null,
  updated_at: "2026-11-19T01:00:00Z",
  completed_at: null,
  ...over,
});
const job = (over: Record<string, unknown> = {}) => ({
  id: ID,
  title: "작업",
  status: "draft" as const,
  failed_stage: null,
  error_code: null,
  rights_confirmed: true,
  license_cc: null,
  credit: null,
  source_start_sec: 5,
  segment_len_sec: 30,
  ...over,
});
const form = (j: ReturnType<typeof job> | null, extra: Record<string, unknown> = {}) =>
  renderToStaticMarkup(<SourceForm job={j} candidate={null} hasReadySource={false} {...extra} />);

describe("PROD-00 목록 상태", () => {
  it("빈 상태: 안내 문구와 소재수집 열기", () => {
    const html = renderToStaticMarkup(<EmptyJobs />);
    expect(html).toContain("내부 제작");
    expect(html).toMatch(/<a[^>]*href="\/monitor"[^>]*>소재수집 열기<\/a>/);
  });
  it("필터 결과 없음: 필터 지우기", () => {
    expect(renderToStaticMarkup(<NoFilterResult />)).toMatch(/href="\/production"[^>]*>필터 지우기/);
  });
  it("오류: role=alert + 다시 시도", () => {
    const html = renderToStaticMarkup(<JobsError message="잠시" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("다시 시도");
  });
  it("로딩 스켈레톤", () => {
    expect(renderToStaticMarkup(<JobsSkeleton />)).toContain('role="status"');
  });
  it("목록: 제목 이스케이프, 상태 라벨, 실패 사유", () => {
    const html = renderToStaticMarkup(
      <JobTable items={[item(), item({ id: "x", status: "failed", failed_stage: "prepare", error_code: "ffprobe_failed" })]} status={null} page={1} />,
    );
    expect(html).not.toContain("<b>x</b>");
    expect(html).toContain("&lt;b&gt;x&lt;/b&gt;");
    expect(html).toContain("초안");
    expect(html).toContain("실패");
    expect(html).toContain("ffprobe_failed");
  });
  it("상태 필터 현재 항목 aria-current, 잘못된 값은 전체", () => {
    expect(renderToStaticMarkup(<StatusFilter status="review" />)).toMatch(/aria-current="page"[^>]*>편집안 검토/);
    expect(parseStatus("evil")).toBeNull();
    expect(parseStatus("done")).toBe("done");
  });
  it("행 이동: 초안·준비 실패는 PROD-01", () => {
    expect(jobHref(item())).toBe(`/production/${ID}/source`);
    expect(jobHref(item({ status: "failed", failed_stage: "prepare" }))).toBe(`/production/${ID}/source`);
    expect(jobHref(item({ status: "failed", failed_stage: "render" }))).toBe(`/production/${ID}`);
    expect(jobHref(item({ status: "review" }))).toBe(`/production/${ID}`);
  });
});

describe("PROD-01 폼 상태", () => {
  it("첫 입력: 형식 카테고리형 고정, URL 안내, 편집안으로 비활성", () => {
    const html = form(null);
    expect(html).toContain("카테고리형");
    expect(html).toContain("0 초과 180 이하");
    expect(html).toContain("원본 URL 입력은 아직 지원하지 않습니다");
    expect(html).toMatch(/<button[^>]*\sdisabled=""[^>]*>편집안으로<\/button>/);
    expect(html).toMatch(/<button type="submit"[^>]*>원본 준비 시작<\/button>/);
    expect(html).not.toMatch(/type="submit"[^>]*\sdisabled=""/);
  });
  it("작업이 있으면 제목은 읽기 전용 + 안내, 생성 전에는 편집 가능", () => {
    const html = form(job());
    expect(html).toMatch(/<input id="src-title"[^>]*\sreadonly=""/i);
    expect(html).toContain("제목은 생성 후 바꿀 수 없습니다");
    const fresh = form(null);
    expect(fresh).not.toMatch(/<input id="src-title"[^>]*\sreadonly=""/i);
    expect(fresh).not.toContain("제목은 생성 후");
  });
  it("후보 정보로 제목·라이선스를 채운다", () => {
    const c = { id: ID, title: "후보 제목", license_cc: true };
    const html = renderToStaticMarkup(<SourceForm job={null} candidate={c} hasReadySource={false} />);
    expect(html).toContain('value="후보 제목"');
    expect(renderToStaticMarkup(<CandidateCard candidate={c} />)).toContain("CC(재사용 허용)");
  });
  it("준비 중: 입력·버튼 잠금, 원본 준비 중 표시, 편집안으로 비활성", () => {
    const html = form(job({ status: "preparing" }));
    expect(html).toContain("원본 준비 중");
    expect(html).toMatch(/<button type="submit"[^>]*\sdisabled=""/);
    expect(html).toContain("형식은 바꿀 수 없음");
    expect(html).toMatch(/<button[^>]*\sdisabled=""[^>]*>편집안으로<\/button>/);
  });
  it("준비 실패: 사유와 다시 시작", () => {
    const html = form(job({ status: "failed", failed_stage: "prepare", error_code: "ffprobe_failed" }), { hasReadySource: true });
    expect(html).toContain("ffprobe_failed");
    expect(html).toContain("원본 준비 다시 시작");
    expect(isEditable({ status: "failed", failed_stage: "prepare" })).toBe(true);
    expect(isEditable({ status: "failed", failed_stage: "render" })).toBe(false);
  });
  it("준비 완료: 편집안으로 링크 활성", () => {
    const html = form(job({ status: "review" }), { hasReadySource: true });
    expect(html).toMatch(new RegExp(`<a[^>]*href="/production/${ID}/edit"[^>]*>편집안으로</a>`));
    expect(html).toMatch(/<button type="submit"[^>]*\sdisabled=""/);
  });
});

describe("순수 함수", () => {
  const base = { title: "t", start: "0", len: "30", rights: true, hasFile: true, hasReadySource: false };
  it("구간·권한·파일 검증", () => {
    expect(validateSource(base, true)).toEqual({});
    expect(validateSource({ ...base, len: "181" }, true).len).toBeTruthy();
    expect(validateSource({ ...base, len: "0" }, true).len).toBeTruthy();
    expect(validateSource({ ...base, len: "" }, true).len).toBeTruthy();
    expect(validateSource({ ...base, start: "-1" }, true).start).toBeTruthy();
    expect(validateSource({ ...base, rights: false }, true).rights).toBeTruthy();
    expect(validateSource({ ...base, hasFile: false }, true).file).toBeTruthy();
    expect(validateSource({ ...base, hasFile: false }, false).file).toBeUndefined();
    expect(validateSource({ ...base, hasFile: false, hasReadySource: true }, true).file).toBeUndefined();
  });
  it("mime·후보 링크", () => {
    expect(mimeOf({ name: "a.MKV", type: "" })).toBe("video/x-matroska");
    expect(mimeOf({ name: "a.exe", type: "video/mp4" })).toBeNull();
    const href = candidateHref({ id: ID, title: "a&b=c", license_cc: false });
    expect(href).toBe(`/production/new?candidate_id=${ID}&title=a%26b%3Dc&license=other`);
    expect(candidateHref({ id: ID, title: "t", license_cc: null })).not.toContain("license");
  });
});

describe("브라우저 호출", () => {
  it("생성은 멱등 키 헤더, 네트워크 오류는 키 유지", async () => {
    let seen: RequestInit | undefined;
    const ok = (async (_u: string, init?: RequestInit) => {
      seen = init;
      return new Response('{"job":{"id":"j","status":"draft"}}', { status: 200 });
    }) as typeof fetch;
    const body = { title: "t", rights_confirmed: true, license_cc: null, credit: null, source_start_sec: 0, segment_len_sec: 1 };
    expect((await createJob(body, "key-12345678", ok)).ok).toBe(true);
    expect((seen?.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-12345678");
    const down = (async () => {
      throw new TypeError("x");
    }) as typeof fetch;
    expect(await createJob(body, "k", down)).toMatchObject({ ok: false, keepKey: true });
    const conflict = (async () => new Response('{"message":"상태 불가: preparing"}', { status: 409 })) as typeof fetch;
    expect(await createJob(body, "k", conflict)).toMatchObject({ ok: false, status: 409, keepKey: false, message: "상태 불가: preparing" });
  });
  it("PUT 실패는 false", async () => {
    expect(await putFile("https://s/u", new Blob(["x"]), "video/mp4", (async () => new Response("", { status: 400 })) as typeof fetch)).toBe(false);
  });
});
