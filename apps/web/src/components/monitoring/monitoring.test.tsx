import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }), redirect: vi.fn() }));

const { CandidateResults, CandidateSkeleton, MonitorError, StatusStats } = await import("./monitor-view");
const { JobPanel } = await import("./job-panel");
const { MonitorWorkbench, fetchJobStatus, finishedNotice } = await import("./monitor-workbench");
const { safeThumbnailUrl } = await import("./thumbnail");
const { parseCandidateQuery, toHref, DEFAULT_QUERY } = await import("./query");
const { toActionFailure, FAILED_MESSAGE, QUOTA_MESSAGE, RATE_LIMITED_MESSAGE, VERIFY_TIMEOUT_MESSAGE, WORKER_OFFLINE_MESSAGE, chromeDetailLabel } =
  await import("./messages");
const { createIntentKey, createIntentRunner, idsFingerprint } = await import("./intent-key");
const { createPoller, nextDelay, POLL_MS, OFFLINE_POLL_MS, MAX_BACKOFF_MS } = await import("./poller");
const { pickJob } = await import("./job");

type Data = Parameters<typeof CandidateResults>[0]["data"];
type Item = Data["items"][number];
type Job = import("./job").JobView;

const P1 = "00000000-0000-4000-8000-0000000000a1";
const P2 = "00000000-0000-4000-8000-0000000000a2";
const JOB_ID = "00000000-0000-4000-8000-0000000000f1";

const item = (over: Partial<Item> = {}): Item => ({
  id: "00000000-0000-4000-8000-000000000c01",
  thumbnail_url: "https://i.ytimg.com/vi/abc/hqdefault.jpg",
  status: "producible",
  genre: "예능",
  title: "정상 제목",
  format: "short",
  profile_names: ["한국 예능"],
  license_cc: true,
  prev: { observed_at: "2026-11-09T00:00:00Z", view_count: 1000 },
  curr: { observed_at: "2026-11-16T00:00:00Z", view_count: 1010 },
  growth_pct: 1,
  period_days: 7,
  next_observation_at: null,
  used: false,
  ...over,
});
const counts = { total: 0, producible: 0, pending: 0, excluded: 0, used: 0 };
const data = (items: Item[], c = counts): Data => ({ counts: c, categories: ["예능"], items, updated_at: "2026-11-17T00:00:00Z" });
const job = (over: Partial<Job> = {}): Job => ({
  id: JOB_ID,
  status: "running",
  error: null,
  stop_requested: false,
  retry_count: 0,
  profiles: [{ profile_id: P1, chrome_state: "ready", detail: null, status: "running", collected_count: 3 }],
  result: { candidates: 0, producible: 0, pending: 0 },
  worker_online: true,
  ...over,
});
const noop = () => {};
const names: Record<string, string> = { [P1]: "한국 예능", [P2]: "일본 예능" };

describe("후보 목록 상태", () => {
  it("빈: 후보 없음 → '후보 가져오기' 안내", () => {
    const html = renderToStaticMarkup(<CandidateResults data={data([])} query={DEFAULT_QUERY} opsUrl="https://ops.example.com/" />);
    expect(html).toContain("아직 가져온 후보가 없습니다");
    expect(html).toContain("후보 가져오기");
  });

  it("빈(필터 결과 없음): 필터 초기화", () => {
    const q = parseCandidateQuery({ status: "pending" });
    const html = renderToStaticMarkup(<CandidateResults data={data([], { ...counts, total: 3 })} query={q} opsUrl="" />);
    expect(html).toContain("선택한 조건에 맞는 후보가 없습니다");
    expect(html).toContain("필터 초기화");
  });

  it("로딩: 카드 스켈레톤", () => {
    const html = renderToStaticMarkup(<CandidateSkeleton />);
    expect(html).toContain('role="status"');
    expect(html).toContain("animate-pulse");
  });

  it("오류: 다시 시도", () => {
    const html = renderToStaticMarkup(<MonitorError title="후보를 불러오지 못했습니다" message="잠시 후 다시 시도하세요." />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("다시 시도");
  });

  it("성공: 카드 필드·영상 만들기(고정 주소·새 탭)·관측 근거 비활성", () => {
    const html = renderToStaticMarkup(
      <CandidateResults data={data([item()], { ...counts, total: 1, producible: 1 })} query={DEFAULT_QUERY} opsUrl="https://ops.example.com/" />,
    );
    expect(html).toContain("제작 가능");
    expect(html).toContain("쇼츠 · 한국 예능 · C.C 확인");
    expect(html).toContain("+1.0%");
    expect(html).toContain('href="https://ops.example.com/"');
    expect(html).toContain('rel="noopener noreferrer"');
    // 보이는 "준비 중" 설명을 aria-describedby로 연결, 숨은 title·disabled 없음
    const btn = html.match(/<button[^>]*>관측 근거<\/button>/)?.[0] ?? "";
    expect(btn).toContain('aria-disabled="true"');
    expect(btn).not.toContain("title=");
    expect(btn).not.toContain(' disabled=""');
    const id = btn.match(/aria-describedby="([^"]+)"/)?.[1];
    expect(html).toMatch(new RegExp(`id="${id}"[^>]*>준비 중<`));
  });

  it("근거 대기: 이전 관측값 필요 + 다음 관측 예정 시각, 영상 만들기 없음", () => {
    const html = renderToStaticMarkup(
      <CandidateResults
        data={data([item({ status: "pending", prev: null, next_observation_at: "2026-11-18T00:30:00Z" })], { ...counts, total: 1, pending: 1 })}
        query={DEFAULT_QUERY}
        opsUrl="https://ops.example.com/"
      />,
    );
    expect(html).toContain("이전 관측값 필요");
    expect(html).toContain("다음 관측 예정");
    expect(html).toContain("09:30");
    expect(html).not.toContain("영상 만들기");
  });

  it("<script> 제목·장르·프로필명은 텍스트로 렌더", () => {
    const evil = "<script>alert(1)</script>";
    const html = renderToStaticMarkup(
      <CandidateResults data={data([item({ title: evil, genre: evil, profile_names: [evil] })], { ...counts, total: 1 })} query={DEFAULT_QUERY} opsUrl="" />,
    );
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  });

  it("허용 외 썸네일 host는 img 대신 자리 표시", () => {
    const html = renderToStaticMarkup(
      <CandidateResults data={data([item({ thumbnail_url: "https://evil.example.com/x.jpg" })], { ...counts, total: 1 })} query={DEFAULT_QUERY} opsUrl="" />,
    );
    expect(html).not.toContain("<img");
    expect(html).toContain('data-thumb="placeholder"');
    const ok = renderToStaticMarkup(<CandidateResults data={data([item()], { ...counts, total: 1 })} query={DEFAULT_QUERY} opsUrl="" />);
    expect(ok).toContain('src="https://i.ytimg.com/vi/abc/hqdefault.jpg"');
    expect(ok).toContain('referrerPolicy="no-referrer"');
  });

  it("상태 지표는 필터 링크(aria-current)", () => {
    const html = renderToStaticMarkup(<StatusStats counts={{ ...counts, total: 5, used: 2 }} query={parseCandidateQuery({ status: "used" })} />);
    expect(html).toContain('href="?status=producible"');
    expect(html).toMatch(/aria-current="true"[^>]*>.*사용한 소재/);
  });
});

describe("safeThumbnailUrl", () => {
  it.each([
    ["https://i.ytimg.com/vi/a/0.jpg", true],
    ["http://i.ytimg.com/vi/a/0.jpg", false],
    ["https://i.ytimg.com.evil.com/a.jpg", false],
    ["https://evil.com/i.ytimg.com/a.jpg", false],
    ["https://user:pw@i.ytimg.com/a.jpg", false],
    ["https://i.ytimg.com:8443/a.jpg", false],
    ["javascript:alert(1)", false],
    ["", false],
    [null, false],
  ])("%s → %s", (url, ok) => {
    expect(safeThumbnailUrl(url) !== null).toBe(ok);
  });
});

describe("Chrome 준비 결과·진행", () => {
  it("진행: 프로필별 상태·수집 중지", () => {
    const html = renderToStaticMarkup(<JobPanel job={job()} profileNames={names} busy={null} onRetry={noop} onStop={noop} />);
    expect(html).toContain("후보 가져오는 중");
    expect(html).toContain("한국 예능");
    expect(html).toContain("준비 완료");
    expect(html).toContain("3개");
    expect(html).toContain("수집 중지");
    expect(html).not.toContain("해당 후보부터 재시도");
  });

  it("Chrome 실패: 프로필별 원인 + 해당 후보부터 재시도", () => {
    const failed = job({
      status: "failed",
      error: "chrome_failed",
      profiles: [
        { profile_id: P1, chrome_state: "ready", detail: null, status: "done", collected_count: 5 },
        { profile_id: P2, chrome_state: "resize_needed", detail: "window_small", status: "failed", collected_count: 0 },
      ],
    });
    const html = renderToStaticMarkup(<JobPanel job={failed} profileNames={names} busy={null} onRetry={noop} onStop={noop} />);
    expect(html).toContain("창 확대 필요");
    expect(html).toContain("Chrome 창이 작습니다");
    expect(html).toContain("수집 실패: Chrome 준비 실패");
    expect(html).toContain("해당 후보부터 재시도");
    expect(html).not.toContain("수집 중지");
  });

  it("재시도 한도 3회면 재시도 버튼 없음", () => {
    const html = renderToStaticMarkup(<JobPanel job={job({ status: "failed", retry_count: 3 })} profileNames={names} busy={null} onRetry={noop} onStop={noop} />);
    expect(html).not.toContain("해당 후보부터 재시도");
    expect(html).toContain("재시도 한도");
  });

  it("워커 오프라인: queued + worker_online=false → 안내와 수집 중지", () => {
    const html = renderToStaticMarkup(
      <JobPanel job={job({ status: "queued", worker_online: false })} profileNames={names} busy={null} onRetry={noop} onStop={noop} />,
    );
    expect(html).toContain(WORKER_OFFLINE_MESSAGE.replace("—", "—"));
    expect(html).toContain("수집 중지");
  });

  it("모르는 detail 코드는 '알 수 없는 원인'(원문 노출 없음)", () => {
    expect(chromeDetailLabel("<b>x</b>")).toBe("알 수 없는 원인");
    expect(chromeDetailLabel(null)).toBeNull();
  });

  it("완료 토스트: 후보 N개 가져옴 · 제작 가능 N · 근거 대기 N", () => {
    expect(finishedNotice(job({ status: "done", result: { candidates: 7, producible: 2, pending: 3 } })).text).toBe(
      "후보 7개 가져옴 · 제작 가능 2 · 근거 대기 3",
    );
  });
});

describe("MonitorWorkbench", () => {
  const profile = (id: string, selected: boolean) => ({
    id,
    name: names[id],
    market: "KR" as const,
    format: "short" as const,
    category: null,
    min_views: 0,
    max_growth_pct: 5,
    keywords: [],
    cc_only: false,
    include_broadcast: true,
    selected,
    updated_at: "2026-11-17T00:00:00Z",
  });
  const actions = {
    startCollect: vi.fn(),
    retryCollect: vi.fn(),
    stopCollect: vi.fn(),
    verifyRecords: vi.fn(),
    saveConditions: vi.fn(),
    saveSelection: vi.fn(),
  };
  const render = (props: Partial<Parameters<typeof MonitorWorkbench>[0]> = {}) =>
    renderToStaticMarkup(
      <MonitorWorkbench
        profiles={[profile(P1, true), profile(P2, false)]}
        profilesError={null}
        activeJob={null}
        actions={actions}
        sessionExpiredPath="/dashboard/session-expired"
        updated={null}
        {...props}
      >
        <p>후보 영역</p>
      </MonitorWorkbench>,
    );
  const buttons = (html: string) => html.match(/<button[^>]*>(후보 가져오기|후보 가져오는 중…|기록 검증 실행)<\/button>/g) ?? [];

  it("기본: 두 버튼 활성, 프로필 카드(조건 설정)", () => {
    const html = render();
    expect(buttons(html)).toHaveLength(2);
    expect(buttons(html).every((b) => !b.includes(' disabled=""'))).toBe(true);
    expect(html).toContain("조건 설정");
    expect(html).toContain("후보 영역");
  });

  it("진행(활성 job 복구): 두 버튼 비활성 + 스켈레톤", () => {
    const html = render({ activeJob: job({ status: "queued" }) });
    expect(buttons(html)).toHaveLength(2);
    expect(buttons(html).every((b) => b.includes(' disabled=""'))).toBe(true);
    expect(html).toContain("후보 가져오는 중");
    expect(html).toContain("animate-pulse");
  });

  it("조건 미설정(선택 0개): 안내 + 버튼 비활성", () => {
    const html = render({ profiles: [profile(P1, false)] });
    expect(html).toContain("&#x27;조건 설정&#x27;");
    expect(buttons(html).every((b) => b.includes(' disabled=""'))).toBe(true);
  });

  it("프로필 오류: 다시 시도", () => {
    const html = render({ profiles: null, profilesError: "서버에 연결하지 못했습니다." });
    expect(html).toContain("프로필을 불러오지 못했습니다");
    expect(html).toContain("다시 시도");
  });
});

describe("searchParams 정규화", () => {
  it("잘못된 값은 기본값, 배열은 첫 값", () => {
    expect(parseCandidateQuery({ status: "hack", sort: ["views", "growth"], page: "0", format: "x", license: "all", profile_id: "1 or 1" })).toEqual(
      { ...DEFAULT_QUERY, sort: "views" },
    );
    expect(parseCandidateQuery({ page: "1001" }).page).toBe(1);
    expect(parseCandidateQuery({ page: "2.5" }).page).toBe(1);
    expect(parseCandidateQuery({ page: "7" }).page).toBe(7);
    expect(parseCandidateQuery({ profile_id: P1.toUpperCase() }).profile_id).toBe(P1);
  });

  it("q는 제어 문자 제거·100자 자르기, 공백뿐이면 빈 값", () => {
    expect(parseCandidateQuery({ q: "a\u0000b\u001fc\u007f" }).q).toBe("abc");
    expect([...parseCandidateQuery({ q: "가".repeat(150) }).q]).toHaveLength(100);
    expect(parseCandidateQuery({ q: "   " }).q).toBe("");
  });

  it("toHref: 기본값 생략, 필터 변경 시 page 초기화", () => {
    const q = parseCandidateQuery({ status: "pending", page: "3" });
    expect(toHref(q, { sort: "growth" })).toBe("?status=pending&sort=growth");
    expect(toHref(q, { page: 4 })).toBe("?status=pending&page=4");
    expect(toHref(DEFAULT_QUERY)).toBe("?");
  });
});

describe("오류 문구", () => {
  it("429 두 종류는 code별 고정 문구", () => {
    expect(toActionFailure({ status: 429, code: "QUOTA_EXCEEDED", message: "x" })).toMatchObject({ message: QUOTA_MESSAGE, keepKey: false });
    expect(toActionFailure({ status: 429, code: "RATE_LIMITED", message: "x" })).toMatchObject({ message: RATE_LIMITED_MESSAGE, keepKey: false });
  });

  it("400·409는 API 고정 문구, 키 교체", () => {
    expect(toActionFailure({ status: 409, code: "CONFLICT", message: "수집이 이미 진행 중입니다." })).toEqual({
      ok: false,
      message: "수집이 이미 진행 중입니다.",
      keepKey: false,
    });
  });

  it("기록 검증 타임아웃은 진행 중 안내 + 키 유지, 연결 실패·5xx도 키 유지", () => {
    expect(toActionFailure({ status: 0, code: "TIMEOUT", message: "t" }, { verify: true })).toMatchObject({
      message: VERIFY_TIMEOUT_MESSAGE,
      keepKey: true,
    });
    expect(toActionFailure({ status: 0, code: "NETWORK", message: "n" }).keepKey).toBe(true);
  });

  it("API message는 400·409만, 5xx·403·404·연결 실패는 고정 문구", () => {
    expect(toActionFailure({ status: 400, code: "VALIDATION", message: "수집할 프로필이 없습니다." }).message).toBe("수집할 프로필이 없습니다.");
    for (const status of [0, 403, 404, 500, 502, 503, 418]) {
      expect(toActionFailure({ status, code: "X", message: "내부 오류 상세 <b>" }).message).toBe(FAILED_MESSAGE);
    }
    expect(toActionFailure({ status: 404, code: "NOT_FOUND", message: "x" }).keepKey).toBe(false);
    expect(toActionFailure({ status: 503, code: "X", message: "x" }).keepKey).toBe(true);
    expect(toActionFailure({ status: 502, code: "UPSTREAM_ERROR", message: "u" }).keepKey).toBe(true);
  });
});

describe("Idempotency-Key", () => {
  it("성공·확정 오류 뒤 새 키, 재시도 가능 오류 뒤 같은 키", async () => {
    let n = 0;
    const runner = createIntentRunner(() => `k${++n}`);
    const keys: string[] = [];
    const send = (res: { ok: boolean; keepKey?: boolean }) => async (key: string) => {
      keys.push(key);
      return res;
    };
    await runner.run("fp", send({ ok: false, keepKey: true })); // 타임아웃
    await runner.run("fp", send({ ok: true })); // 같은 키로 성공
    await runner.run("fp", send({ ok: false, keepKey: false })); // 새 키, 4xx
    await runner.run("fp", send({ ok: true })); // 새 키
    expect(keys).toEqual(["k1", "k1", "k2", "k3"]);
  });

  it("요청 중 중복 클릭은 보내지 않는다", async () => {
    const runner = createIntentRunner(() => "k");
    let release: () => void = noop;
    const calls: string[] = [];
    const first = runner.run("fp", (key) => {
      calls.push(key);
      return new Promise<{ ok: true }>((r) => (release = () => r({ ok: true })));
    });
    expect(runner.busy).toBe(true);
    expect(await runner.run("fp", async (key) => (calls.push(key), { ok: true }))).toBeNull();
    release();
    await first;
    expect(calls).toEqual(["k"]);
    expect(runner.busy).toBe(false);
  });

  it("전송 예외면 키 유지", async () => {
    let n = 0;
    const key = createIntentKey(() => `k${++n}`);
    expect(key.current("fp")).toBe("k1");
    key.settle(true);
    expect(key.current("fp")).toBe("k1");
    key.settle(false);
    expect(key.current("fp")).toBe("k2");
    const runner = createIntentRunner(() => `r${++n}`);
    const seen: string[] = [];
    await expect(runner.run("fp", async (k) => (seen.push(k), Promise.reject(new Error("x"))))).rejects.toThrow();
    await runner.run("fp", async (k) => (seen.push(k), { ok: true }));
    expect(seen[0]).toBe(seen[1]);
  });

  it("요청 본문 지문(profile_ids 정렬)이 바뀌면 키를 유지 중이어도 새 키", async () => {
    let n = 0;
    const runner = createIntentRunner(() => `k${++n}`);
    const keys: string[] = [];
    const send = async (key: string) => (keys.push(key), { ok: false, keepKey: true });
    await runner.run(idsFingerprint([P2, P1]), send); // 타임아웃 → 키 유지
    await runner.run(idsFingerprint([P1, P2, P1]), send); // 같은 조합(순서·중복 무관) → 같은 키
    await runner.run(idsFingerprint([P1]), send); // 다른 조합 → 새 키
    await runner.run(idsFingerprint([P1, P2]), send); // 다시 바뀜 → 새 키
    expect(keys).toEqual(["k1", "k1", "k2", "k3"]);
    expect(idsFingerprint([P2, P1.toUpperCase()])).toBe(`${P1},${P2}`);
  });
});

describe("폴링", () => {
  function harness(results: (Awaited<ReturnType<typeof fetchJobStatus>> | Promise<never>)[]) {
    const timers: { cb: () => void; ms: number }[] = [];
    let hidden = false;
    let visCb: (() => void) | null = null;
    const deps = {
      fetchJob: vi.fn(async () => {
        const r = results.shift();
        if (!r) throw new Error("no result");
        return r;
      }),
      onJob: vi.fn(),
      onFinished: vi.fn(),
      onUnauthorized: vi.fn(),
      onGone: vi.fn(),
      isHidden: () => hidden,
      onVisibilityChange: (cb: () => void) => {
        visCb = cb;
        return () => {
          visCb = null;
        };
      },
      setTimer: (cb: () => void, ms: number) => {
        const t = { cb, ms };
        timers.push(t);
        return t;
      },
      clearTimer: (h: unknown) => {
        const i = timers.indexOf(h as (typeof timers)[number]);
        if (i >= 0) timers.splice(i, 1);
      },
    };
    const poller = createPoller(deps);
    const fire = async () => {
      const t = timers.shift();
      if (!t) throw new Error("no timer");
      t.cb();
      await new Promise((r) => setTimeout(r, 0));
      return t.ms;
    };
    return {
      deps,
      poller,
      timers,
      fire,
      setHidden: (h: boolean) => {
        hidden = h;
        visCb?.();
      },
      hasVisibilityListener: () => visCb !== null,
    };
  }

  it("3초 간격, 종료 상태면 멈추고 onFinished", async () => {
    const h = harness([{ kind: "ok", job: job() }, { kind: "ok", job: job({ status: "done" }) }]);
    h.poller.start(JOB_ID);
    expect(await h.fire()).toBe(POLL_MS);
    expect(h.deps.onJob).toHaveBeenCalledTimes(1);
    expect(await h.fire()).toBe(POLL_MS);
    expect(h.deps.onFinished).toHaveBeenCalledWith(expect.objectContaining({ status: "done" }));
    expect(h.timers).toHaveLength(0);
    expect(h.poller.running).toBe(false);
    expect(h.hasVisibilityListener()).toBe(false);
  });

  it("탭이 숨겨지면 멈추고, 보이면 바로 다시 요청", async () => {
    const h = harness([{ kind: "ok", job: job() }]);
    h.poller.start(JOB_ID);
    h.setHidden(true);
    expect(h.timers).toHaveLength(0);
    expect(h.deps.fetchJob).not.toHaveBeenCalled();
    h.setHidden(false);
    await new Promise((r) => setTimeout(r, 0));
    expect(h.deps.fetchJob).toHaveBeenCalledTimes(1);
    expect(h.timers.map((t) => t.ms)).toEqual([POLL_MS]);
    h.poller.stop();
  });

  it("오류면 간격 2배(최대 30초), 성공하면 3초로 복귀", async () => {
    const err = { kind: "error" as const };
    const h = harness([err, err, err, err, { kind: "ok", job: job() }]);
    h.poller.start(JOB_ID);
    await h.fire();
    expect(h.timers[0].ms).toBe(6_000);
    await h.fire();
    expect(h.timers[0].ms).toBe(12_000);
    await h.fire();
    expect(h.timers[0].ms).toBe(24_000);
    await h.fire();
    expect(h.timers[0].ms).toBe(MAX_BACKOFF_MS);
    await h.fire();
    expect(h.timers[0].ms).toBe(POLL_MS);
    h.poller.stop();
  });

  it("queued + 워커 오프라인이면 10초", () => {
    expect(nextDelay(job({ status: "queued", worker_online: false }), 0)).toBe(OFFLINE_POLL_MS);
    expect(nextDelay(job({ status: "running", worker_online: false }), 0)).toBe(POLL_MS);
  });

  it("이전 요청이 끝나기 전에는 새로 보내지 않는다", async () => {
    let release: (v: Awaited<ReturnType<typeof fetchJobStatus>>) => void = noop;
    const h = harness([new Promise<never>(() => {})]);
    h.deps.fetchJob.mockImplementationOnce(() => new Promise((r) => (release = r)));
    h.poller.start(JOB_ID);
    h.timers[0].cb(); // 요청 시작(대기)
    h.timers.length = 0;
    h.setHidden(true);
    h.setHidden(false); // 보이게 돼도 진행 중이면 새 요청 없음
    expect(h.deps.fetchJob).toHaveBeenCalledTimes(1);
    release({ kind: "ok", job: job() });
    await new Promise((r) => setTimeout(r, 0));
    expect(h.timers.map((t) => t.ms)).toEqual([POLL_MS]);
    h.poller.stop();
  });

  it("403·404(gone)면 멈추고 onGone(활성 job 다시 받기), onUnauthorized는 아님", async () => {
    const h = harness([{ kind: "gone" }]);
    h.poller.start(JOB_ID);
    await h.fire();
    expect(h.deps.onGone).toHaveBeenCalledTimes(1);
    expect(h.deps.onUnauthorized).not.toHaveBeenCalled();
    expect(h.timers).toHaveLength(0);
    expect(h.poller.running).toBe(false);
  });

  it("401이면 멈추고 onUnauthorized", async () => {
    const h = harness([{ kind: "unauthorized" }]);
    h.poller.start(JOB_ID);
    await h.fire();
    expect(h.deps.onUnauthorized).toHaveBeenCalled();
    expect(h.timers).toHaveLength(0);
  });

  it("stop 뒤 늦게 온 응답은 무시(언마운트 정리)", async () => {
    let release: (v: Awaited<ReturnType<typeof fetchJobStatus>>) => void = noop;
    const h = harness([]);
    h.deps.fetchJob.mockImplementationOnce(() => new Promise((r) => (release = r)));
    h.poller.start(JOB_ID);
    h.timers.shift()!.cb();
    h.poller.stop();
    release({ kind: "ok", job: job({ status: "done" }) });
    await new Promise((r) => setTimeout(r, 0));
    expect(h.deps.onJob).not.toHaveBeenCalled();
    expect(h.deps.onFinished).not.toHaveBeenCalled();
    expect(h.timers).toHaveLength(0);
  });

  it("fetchJobStatus: 401 JSON → unauthorized, 200 → 화면 필드", async () => {
    const f401 = vi.fn(async () => new Response(JSON.stringify({ code: "UNAUTHENTICATED" }), { status: 401 }));
    expect(await fetchJobStatus(JOB_ID, f401 as unknown as typeof fetch)).toEqual({ kind: "unauthorized" });
    const f200 = vi.fn(async () => new Response(JSON.stringify({ job: { ...job(), secret: "x" } }), { status: 200 }));
    const res = await fetchJobStatus(JOB_ID, f200 as unknown as typeof fetch);
    expect(res.kind).toBe("ok");
    expect(res.kind === "ok" && "secret" in res.job).toBe(false);
    for (const status of [403, 404]) {
      const f = vi.fn(async () => new Response(JSON.stringify({ code: "NOT_FOUND" }), { status }));
      expect(await fetchJobStatus(JOB_ID, f as unknown as typeof fetch)).toEqual({ kind: "gone" });
    }
    const f500 = vi.fn(async () => new Response("", { status: 502 }));
    expect(await fetchJobStatus(JOB_ID, f500 as unknown as typeof fetch)).toEqual({ kind: "error" });
  });
});

const { default: MonitorLoading } = await import("@/app/(dashboard)/monitor/loading");
const { CandidateFilters } = await import("./monitor-view");

describe("리뷰 반영(design)", () => {

  it("프로필 카드 제목은 spec대로 '프로필별 수집 조건'", async () => {
    const { ProfileList } = await import("@/components/profiles/profile-list");
    const html = renderToStaticMarkup(
      <ProfileList
        profiles={[
          {
            id: P1,
            name: "한국 예능",
            market: "KR",
            format: "short",
            category: null,
            min_views: 0,
            max_growth_pct: 5,
            keywords: [],
            cc_only: false,
            include_broadcast: true,
            selected: true,
            updated_at: "2026-11-17T00:00:00Z",
          },
        ]}
        saveConditions={vi.fn()}
        saveSelection={vi.fn()}
      />,
    );
    expect(html).toMatch(/<h2 id="profiles-title"[^>]*>프로필별 수집 조건<\/h2>/);
  });

  it("진행 중 result=null(집계 생략)도 처리: 패널 렌더·완료 토스트 0 대체·pickJob", () => {
    expect(pickJob({ ...job(), result: null })?.result).toBeNull();
    const html = renderToStaticMarkup(<JobPanel job={job({ result: null })} profileNames={names} busy={null} onRetry={noop} onStop={noop} />);
    expect(html).toContain("후보 가져오는 중");
    expect(finishedNotice(job({ status: "done", result: null })).text).toBe("후보 0개 가져옴 · 제작 가능 0 · 근거 대기 0");
  });

  it("상태 배지와 프로필별 진행 줄은 aria-live=polite 영역 안, 버튼은 밖", () => {
    const html = renderToStaticMarkup(<JobPanel job={job()} profileNames={names} busy={null} onRetry={noop} onStop={noop} />);
    const live = html.match(/<div aria-live="polite" data-live="job-progress">([\s\S]*)<\/div><div class="mt-3/)?.[1] ?? "";
    expect(live).toContain("후보 가져오는 중"); // 배지
    expect(live).toContain("가져오는 중 · 3개"); // 프로필 진행 줄
    expect(live).not.toContain("수집 중지");
    expect(html).toContain("수집 중지");
  });

  it("loading: '후보 가져오는 중' 라벨 + 프로필별 진행 자리 + 두 버튼 비활성", () => {
    const html = renderToStaticMarkup(<MonitorLoading />);
    expect(html).toContain('aria-label="후보 가져오는 중"');
    expect(html).not.toContain("후보 불러오는 중");
    expect(html).toContain('data-skeleton="progress"');
    expect(html.match(/<button[^>]* disabled=""[^>]*>(후보 가져오기|기록 검증 실행)<\/button>/g)).toHaveLength(2);
  });

  it("모바일 지표: 마지막(사용한 소재) 칸이 2열 차지", () => {
    const html = renderToStaticMarkup(<StatusStats counts={counts} query={DEFAULT_QUERY} />);
    const items = html.match(/<li[^>]*>/g) ?? [];
    expect(items).toHaveLength(5);
    expect(items[4]).toContain("col-span-2 tablet:col-span-1");
    expect(items.slice(0, 4).every((li) => !li.includes("col-span-2"))).toBe(true);
  });

  it("검색·필터: 모바일 접기(details/summary), 태블릿 이상 펼침, 적용 필터 있으면 처음부터 펼침", () => {
    const closed = renderToStaticMarkup(<CandidateFilters query={DEFAULT_QUERY} categories={[]} profiles={[]} />);
    expect(closed).toMatch(/<details class="[^"]*tablet:details-content:\[content-visibility:visible\]"/);
    expect(closed).not.toMatch(/<details[^>]* open=""/);
    expect(closed).toMatch(/<summary class="[^"]*tablet:hidden/);
    const open = renderToStaticMarkup(<CandidateFilters query={parseCandidateQuery({ q: "예능", license: "cc" })} categories={[]} profiles={[]} />);
    expect(open).toMatch(/<details[^>]* open=""/);
    expect(open).toContain("(2개 적용)");
  });
});
