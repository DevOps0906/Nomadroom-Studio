"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import { createIntentKey } from "@/components/monitoring/intent-key";
import type { Affiliate, ProductionStatus, ShoppingBrief, ShoppingVertical } from "@/server/api/production";
import { STAGE_LABEL, STATUS_LABEL, STATUS_TONE, formatBytes } from "../format";
import { createShoppingJob, deleteAsset, patchShoppingJob, prepareJob, uploadAsset, type Result } from "./api";
import {
  MAX_SCENES,
  MAX_SOURCES,
  PRODUCT_TYPE_LABEL,
  SOURCE_ACCEPT,
  VERTICAL_LABEL,
  affiliatesPayload,
  basesFor,
  countSources,
  briefPayload,
  classifyFile,
  findBanned,
  isSourceEditable,
  newRow,
  rightsOf,
  sourceWarnings,
  toBriefDraft,
  validateAffiliates,
  validateBrief,
  validateRow,
  type AffiliateDraft,
  type BriefDraft,
  type BriefErrors,
  type SourceRowDraft,
} from "./model";
import { BTN, BasisSelect, CARD, Field, FOCUS, INPUT, PRIMARY, SECONDARY } from "./ui";

// PROD-01S 원본·브리프(쇼핑). 순서: (생성 | 저장) → 원본별 업로드(권리 포함) → 준비 시작(A-11). 근거: docs/03_SCREENS_UX.md PROD-01S, tasks/task-046.md.

export type ShoppingSourceJob = {
  id: string;
  title: string;
  status: ProductionStatus;
  failed_stage: "prepare" | "audio" | "render" | null;
  error_code: string | null;
  vertical: ShoppingVertical | null;
  brief: ShoppingBrief | null;
  affiliates: Affiliate[];
  comment_keyword: string | null;
};
export type SourceAsset = { id: string; kind: string; status: "pending" | "ready"; size_bytes: number | null };

type Phase = "idle" | "saving" | "uploading" | "preparing";
const PHASE_LABEL: Record<Exclude<Phase, "idle">, string> = { saving: "저장하는 중…", uploading: "원본 업로드 중…", preparing: "원본 준비를 시작하는 중…" };
const KIND_TEXT: Record<string, string> = { source_upload: "영상", image: "사진" };

function RowPreview({ file }: { file: File }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(file);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 브라우저 전용 blob 주소를 만들어 상태로 옮긴다(서버 렌더에는 없음)
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  if (!url) return null;
  const kind = classifyFile(file)?.kind;
  // eslint-disable-next-line @next/next/no-img-element -- 브라우저 메모리의 blob 미리보기라 next/image를 쓸 수 없다
  if (kind === "image") return <img src={url} alt={`${file.name} 미리보기`} className="max-h-40 w-auto rounded-card" />;
  if (kind === "source_upload") return <video src={url} controls preload="metadata" aria-label={`${file.name} 미리보기`} className="max-h-40 w-auto rounded-card" />;
  return null;
}

export function ShoppingSourceForm({
  job,
  assets,
  initialVertical,
}: {
  job: ShoppingSourceJob | null;
  assets: SourceAsset[];
  initialVertical?: ShoppingVertical | null;
}) {
  const router = useRouter();
  const editable = isSourceEditable(job?.status ?? "draft", job?.failed_stage ?? null);
  const preparing = job?.status === "preparing";
  const ready = !!job && ["review", "rendering", "inspect", "done"].includes(job.status);
  const failedPrepare = job?.status === "failed" && job.failed_stage === "prepare";

  const [vertical, setVertical] = useState<ShoppingVertical | "">(job?.vertical ?? initialVertical ?? "");
  const [title, setTitle] = useState(job?.title ?? "");
  const [notBanned, setNotBanned] = useState(false);
  const [brief, setBrief] = useState<BriefDraft>(() => toBriefDraft(job?.brief));
  const [keyword, setKeyword] = useState(job?.comment_keyword ?? "");
  const [affiliates, setAffiliates] = useState<AffiliateDraft[]>(() => (job?.affiliates ?? []).map((a) => ({ lang: a.lang, partner: a.partner, url: a.url })));
  const [rows, setRows] = useState<SourceRowDraft[]>(() => [newRow()]);
  const [errors, setErrors] = useState<{ title?: string; vertical?: string; notBanned?: string; brief?: BriefErrors; affiliates?: Record<number, string>; rows?: Record<string, ReturnType<typeof validateRow>>; sources?: string }>({});
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const busy = phase !== "idle";
  const createdId = useRef<string | null>(null);
  const [created, setCreated] = useState(false);
  // 새 작업에서 업로드는 끝났지만 준비 시작이 실패한 경우: 서버 목록(props)에 아직 없으므로 종류를 기억해 재시도 때 원본 수에 더한다.
  const [uploaded, setUploaded] = useState<string[]>([]);
  const intent = useRef(createIntentKey());
  const locked = !!job || created; // 작업 생성 뒤 제목은 바꿀 수 없고, 분야는 원본 준비 시작 후 잠긴다
  const verticalLocked = (!!job && !editable) || busy;
  const lock = !editable || busy;

  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [preparing, router]);

  const keptAssets = assets.filter((a) => a.kind === "source_upload" || a.kind === "image");
  const filled = rows.filter((r) => r.file);
  const { count: sourceCount, hasVideo } = countSources(keptAssets, rows, job ? [] : uploaded);
  const banned = findBanned([title, brief.product_name, brief.pain, brief.destination, brief.appeal, brief.avoid, ...brief.scenes, ...brief.facts, keyword]);
  const consentMissing = filled.some((r) => r.has_person && !r.portrait_consent);
  const warnings = sourceWarnings({ sources: sourceCount, banned, consentMissing, hasVideo });

  const setRow = (key: string, p: Partial<SourceRowDraft>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  const setB = (p: Partial<BriefDraft>) => setBrief((b) => ({ ...b, ...p }));
  const setList = (k: "scenes" | "facts", i: number, v: string) => setBrief((b) => ({ ...b, [k]: b[k].map((x, n) => (n === i ? v : x)) }));

  function fail<T>(r: Extract<Result<T>, { ok: false }>) {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return;
    }
    if (r.field === "title") setErrors((e) => ({ ...e, title: r.message }));
    if (r.field === "vertical") setErrors((e) => ({ ...e, vertical: r.message }));
    if (r.field === "banned_category" || r.field === "not_banned_confirmed") setErrors((e) => ({ ...e, notBanned: r.message }));
    setMessage({ tone: "error", text: r.message });
    setPhase("idle");
  }

  async function submit(mode: "save" | "start") {
    if (busy || !editable) return;
    setMessage(null);
    const e: typeof errors = {};
    if (!vertical) e.vertical = "분야를 선택하세요.";
    if (!locked) {
      const t = title.trim();
      if (t.length < 1 || t.length > 200) e.title = "제목은 1~200자로 입력하세요.";
      if (!notBanned) e.notBanned = "금지 품목(의약품·건강기능식품)이 아님을 확인해야 합니다.";
    }
    if (banned) e.notBanned = `금지 품목 키워드(${banned})가 있어 진행할 수 없습니다.`;
    if (vertical && mode === "start") {
      const be = validateBrief(vertical, brief);
      if (Object.keys(be).length > 0) e.brief = be;
    }
    const ae = validateAffiliates(affiliates);
    if (Object.keys(ae).length > 0) e.affiliates = ae;
    if (mode === "start") {
      const re: Record<string, ReturnType<typeof validateRow>> = {};
      for (const r of filled) {
        const v = validateRow(r);
        if (Object.keys(v).length > 0) re[r.key] = v;
      }
      if (Object.keys(re).length > 0) e.rows = re;
      if (sourceCount === 0) e.sources = "원본을 1개 이상 올려 주세요.";
      if (sourceCount > MAX_SOURCES) e.sources = `원본은 최대 ${MAX_SOURCES}개입니다.`;
    }
    setErrors(e);
    if (Object.keys(e).length > 0 || !vertical) return;

    const fields = {
      brief: briefPayload(vertical, brief),
      affiliates: affiliatesPayload(affiliates),
      comment_keyword: keyword.trim() || null,
    };
    setPhase("saving");
    let id = job?.id ?? createdId.current;
    if (!id) {
      const body = { title: title.trim(), vertical, ...fields };
      const r = await createShoppingJob(body.title, { vertical, ...fields }, intent.current.current(JSON.stringify(body)));
      intent.current.settle(!r.ok && r.keepKey);
      if (!r.ok) return fail(r);
      id = createdId.current = r.data.job.id;
      setCreated(true);
    } else {
      const r = await patchShoppingJob(id, { vertical, ...fields });
      if (!r.ok) return fail(r);
    }

    if (mode === "start") {
      setPhase("uploading");
      for (const r of rows.filter((x) => x.file)) {
        const c = classifyFile(r.file!)!;
        setRow(r.key, { status: "uploading", error: null });
        const up = await uploadAsset(id, r.file!, c.kind, c.mime, rightsOf(r));
        if (!up.ok) {
          setRow(r.key, { status: "failed", error: up.message });
          if (up.status === 401) return fail(up);
          setMessage({ tone: "error", text: `원본 업로드에 실패했습니다. 해당 원본의 다시 시도를 눌러 주세요. (${up.message})` });
          setPhase("idle");
          if (job) router.refresh();
          return;
        }
        setRows((rs) => rs.filter((x) => x.key !== r.key));
        if (!job) setUploaded((u) => [...u, c.kind]);
      }
      setPhase("preparing");
      const p = await prepareJob(id);
      if (!p.ok) {
        if (job) router.refresh();
        return fail(p);
      }
    }

    setPhase("idle");
    if (job) {
      setMessage({ tone: "ok", text: mode === "save" ? "저장했습니다." : "원본 준비를 시작했습니다." });
      router.refresh();
    } else {
      router.replace(`/production/${encodeURIComponent(id)}/source`);
    }
  }

  async function removeAsset(assetId: string) {
    if (busy || !job) return;
    setMessage(null);
    const r = await deleteAsset(job.id, assetId);
    if (!r.ok) return fail(r);
    router.refresh();
  }

  return (
    <form
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault();
        void submit("start");
      }}
      className="flex flex-col gap-4 pb-28 tablet:pb-0"
      aria-busy={busy}
    >
      {job && (
        <div className="flex flex-wrap items-center gap-2" aria-live="polite">
          <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", STATUS_TONE[job.status])}>{STATUS_LABEL[job.status]}</span>
          <span className="rounded-chip bg-primary-soft px-2 py-0.5 text-caption font-semibold text-primary-soft-fg">쇼핑{job.vertical ? `·${VERTICAL_LABEL[job.vertical]}` : ""}</span>
          {preparing && <span className="text-body text-text-muted">원본 준비 중</span>}
          {failedPrepare && (
            <span role="alert" className="text-body text-danger">
              {STAGE_LABEL.prepare} 단계 실패{job.error_code ? ` (${job.error_code})` : ""}. 다시 시작할 수 있습니다.
            </span>
          )}
        </div>
      )}

      <section aria-label="분야·제목" className={cn(CARD, "flex flex-col gap-4")}>
        <h2 className="text-h2 font-bold">분야·제목</h2>
        <Field id="sh-vertical" label="분야" required hint={verticalLocked && job ? "분야는 바꿀 수 없음(원본 준비 시작 후 잠금)" : undefined} error={errors.vertical}>
          <select id="sh-vertical" className={INPUT} value={vertical} disabled={verticalLocked} aria-invalid={!!errors.vertical} onChange={(ev) => setVertical(ev.target.value as ShoppingVertical | "")}>
            <option value="">선택</option>
            <option value="product">{VERTICAL_LABEL.product}</option>
            <option value="travel">{VERTICAL_LABEL.travel}</option>
          </select>
        </Field>
        <Field id="sh-title" label="제목" required hint={locked ? "제목은 생성 후 바꿀 수 없습니다" : undefined} error={errors.title}>
          <input id="sh-title" className={INPUT} value={title} maxLength={200} disabled={lock} readOnly={locked} aria-invalid={!!errors.title} onChange={(ev) => setTitle(ev.target.value)} />
        </Field>
        {!locked && (
          <div className="flex items-start gap-2">
            <input id="sh-banned" type="checkbox" className="mt-1 size-5 accent-primary" checked={notBanned} disabled={lock} aria-invalid={!!errors.notBanned} onChange={(ev) => setNotBanned(ev.target.checked)} />
            <div className="flex flex-col gap-1">
              <label htmlFor="sh-banned" className="text-body font-medium text-text">
                금지 품목 아님 확인 <span aria-hidden className="text-danger">*</span>
              </label>
              <p className="text-caption text-text-muted">의약품·건강기능식품이 아닙니다. 저장하지 않는 확인용 체크입니다.</p>
            </div>
          </div>
        )}
        {errors.notBanned && (
          <p role="alert" className="text-caption text-danger">
            {errors.notBanned}
          </p>
        )}
      </section>

      <section aria-label="원본" className={cn(CARD, "flex flex-col gap-3")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">
            원본 ({sourceCount}/{MAX_SOURCES})
          </h2>
          <button type="button" className={SECONDARY} disabled={lock || sourceCount >= MAX_SOURCES} onClick={() => setRows((rs) => [...rs, newRow()])}>
            ＋ 원본
          </button>
        </div>
        <p className="text-caption text-text-muted">영상 또는 사진(여행은 사진 권장). 원본마다 권리 근거를 입력합니다. 샤오홍슈·제휴처 자료는 자동으로 가져오지 않습니다.</p>
        {errors.sources && (
          <p role="alert" className="text-caption text-danger">
            {errors.sources}
          </p>
        )}

        {keptAssets.length > 0 && (
          <ul aria-label="올라간 원본" className="flex flex-col gap-2">
            {keptAssets.map((a, i) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-border bg-bg p-3">
                <span className="text-body">
                  원본 {i + 1} · {KIND_TEXT[a.kind] ?? a.kind}
                  {a.size_bytes ? ` · ${formatBytes(a.size_bytes)}` : ""} · {a.status === "ready" ? "올라감" : "확인 대기"}
                </span>
                <button type="button" className={SECONDARY} disabled={lock} onClick={() => void removeAsset(a.id)} aria-label={`원본 ${i + 1} 삭제`}>
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}

        <ul className="flex flex-col gap-3">
          {rows.map((r, i) => {
            const re = errors.rows?.[r.key] ?? {};
            const cls = r.file ? classifyFile(r.file) : null;
            return (
              <li key={r.key} className="flex flex-col gap-3 rounded-card border border-border bg-bg p-3" aria-label={`새 원본 ${i + 1}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-body font-semibold">
                    새 원본 {i + 1}
                    {cls && <span className="ml-2 text-caption text-text-muted">{KIND_TEXT[cls.kind]}</span>}
                  </span>
                  <button type="button" className={SECONDARY} disabled={lock || r.status === "uploading"} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                    삭제
                  </button>
                </div>
                <Field id={`${r.key}-file`} label="파일 업로드" required hint="영상 mp4·mov·webm·mkv(500MB 이하) 또는 사진 jpg·png·webp(20MB 이하)" error={re.file}>
                  <input id={`${r.key}-file`} type="file" accept={SOURCE_ACCEPT} disabled={lock} aria-invalid={!!re.file} className={cn(INPUT, "py-2")} onChange={(ev) => setRow(r.key, { file: ev.target.files?.[0] ?? null, status: "idle", error: null })} />
                  {r.file && (
                    <p className="text-caption text-text-muted">
                      {r.file.name} · {formatBytes(r.file.size)}
                    </p>
                  )}
                </Field>
                {r.file && <RowPreview file={r.file} />}
                <div className="grid gap-3 tablet:grid-cols-2">
                  <BasisSelect id={`${r.key}-basis`} value={r.basis} bases={cls ? basesFor(cls.kind) : basesFor("source_upload")} disabled={lock} error={re.basis} onChange={(v) => setRow(r.key, { basis: v })} />
                  <Field id={`${r.key}-url`} label="출처 URL" error={re.source_url}>
                    <input id={`${r.key}-url`} inputMode="url" className={INPUT} value={r.source_url} maxLength={2048} disabled={lock} onChange={(ev) => setRow(r.key, { source_url: ev.target.value })} />
                  </Field>
                  <Field id={`${r.key}-author`} label="저작자">
                    <input id={`${r.key}-author`} className={INPUT} value={r.author} maxLength={100} disabled={lock} onChange={(ev) => setRow(r.key, { author: ev.target.value })} />
                  </Field>
                  <Field id={`${r.key}-note`} label="메모">
                    <input id={`${r.key}-note`} className={INPUT} value={r.note} maxLength={500} disabled={lock} onChange={(ev) => setRow(r.key, { note: ev.target.value })} />
                  </Field>
                </div>
                <div className="flex flex-wrap gap-4">
                  <label className="inline-flex min-h-11 items-center gap-2 text-body">
                    <input type="checkbox" className="size-5 accent-primary" checked={r.has_person} disabled={lock} onChange={(ev) => setRow(r.key, { has_person: ev.target.checked, portrait_consent: ev.target.checked ? r.portrait_consent : false })} />
                    사람 등장
                  </label>
                  <label className="inline-flex min-h-11 items-center gap-2 text-body">
                    <input type="checkbox" className="size-5 accent-primary" checked={r.portrait_consent} disabled={lock || !r.has_person} onChange={(ev) => setRow(r.key, { portrait_consent: ev.target.checked })} />
                    초상권 동의
                  </label>
                </div>
                {re.consent && (
                  <p role="alert" className="text-caption text-danger">
                    {re.consent}
                  </p>
                )}
                {r.status === "uploading" && (
                  <p role="status" className="text-caption text-text-muted">
                    업로드 중…
                  </p>
                )}
                {r.status === "failed" && (
                  <p role="alert" className="flex flex-wrap items-center gap-2 text-caption text-danger">
                    업로드 실패: {r.error}
                    <button type="button" className={SECONDARY} disabled={busy} onClick={() => void submit("start")}>
                      다시 시도
                    </button>
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-label="브리프" className={cn(CARD, "flex flex-col gap-4")}>
        <h2 className="text-h2 font-bold">브리프</h2>
        {!vertical ? (
          <p className="text-body text-text-muted">분야를 먼저 선택하세요.</p>
        ) : vertical === "product" ? (
          <>
            <Field id="br-name" label="제품명" required error={errors.brief?.product_name}>
              <input id="br-name" className={INPUT} value={brief.product_name} maxLength={100} disabled={lock} onChange={(ev) => setB({ product_name: ev.target.value })} />
            </Field>
            <Field id="br-pain" label="해결하는 불편 1개" required error={errors.brief?.pain}>
              <input id="br-pain" className={INPUT} value={brief.pain} maxLength={300} disabled={lock} onChange={(ev) => setB({ pain: ev.target.value })} />
            </Field>
          </>
        ) : (
          <>
            <Field id="br-dest" label="목적지" required error={errors.brief?.destination}>
              <input id="br-dest" className={INPUT} value={brief.destination} maxLength={100} disabled={lock} onChange={(ev) => setB({ destination: ev.target.value })} />
            </Field>
            <Field id="br-type" label="상품 종류" required error={errors.brief?.product_type}>
              <select id="br-type" className={INPUT} value={brief.product_type} disabled={lock} onChange={(ev) => setB({ product_type: ev.target.value as BriefDraft["product_type"] })}>
                <option value="">선택</option>
                {(Object.keys(PRODUCT_TYPE_LABEL) as (keyof typeof PRODUCT_TYPE_LABEL)[]).map((k) => (
                  <option key={k} value={k}>
                    {PRODUCT_TYPE_LABEL[k]}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="br-appeal" label="소구점 1개" required error={errors.brief?.appeal}>
              <input id="br-appeal" className={INPUT} value={brief.appeal} maxLength={300} disabled={lock} onChange={(ev) => setB({ appeal: ev.target.value })} />
            </Field>
          </>
        )}

        {vertical && (
          <>
            <fieldset className="flex flex-col gap-2" disabled={lock}>
              <legend className="text-body font-medium text-text">
                실제 장면 3~5개 <span aria-hidden className="text-danger">*</span>
              </legend>
              {brief.scenes.map((s, i) => (
                <div key={i} className="flex gap-2">
                  <input aria-label={`실제 장면 ${i + 1}`} className={INPUT} value={s} maxLength={300} onChange={(ev) => setList("scenes", i, ev.target.value)} />
                  <button type="button" className={SECONDARY} onClick={() => setB({ scenes: brief.scenes.filter((_, n) => n !== i) })} aria-label={`장면 ${i + 1} 삭제`}>
                    삭제
                  </button>
                </div>
              ))}
              <div>
                <button type="button" className={SECONDARY} disabled={brief.scenes.length >= MAX_SCENES} onClick={() => setB({ scenes: [...brief.scenes, ""] })}>
                  ＋ 장면
                </button>
              </div>
              {errors.brief?.scenes && (
                <p role="alert" className="text-caption text-danger">
                  {errors.brief.scenes}
                </p>
              )}
            </fieldset>
            {vertical === "product" && (
              <Field id="br-avoid" label="빼야 할 말">
                <input id="br-avoid" className={INPUT} value={brief.avoid} maxLength={300} disabled={lock} onChange={(ev) => setB({ avoid: ev.target.value })} />
              </Field>
            )}
            <fieldset className="flex flex-col gap-2" disabled={lock}>
              <legend className="text-body font-medium text-text">확인된 사실</legend>
              {brief.facts.map((s, i) => (
                <div key={i} className="flex gap-2">
                  <input aria-label={`확인된 사실 ${i + 1}`} className={INPUT} value={s} maxLength={300} onChange={(ev) => setList("facts", i, ev.target.value)} />
                  <button type="button" className={SECONDARY} onClick={() => setB({ facts: brief.facts.length > 1 ? brief.facts.filter((_, n) => n !== i) : [""] })} aria-label={`사실 ${i + 1} 삭제`}>
                    삭제
                  </button>
                </div>
              ))}
              <div>
                <button type="button" className={SECONDARY} disabled={brief.facts.length >= 10} onClick={() => setB({ facts: [...brief.facts, ""] })}>
                  ＋ 사실
                </button>
              </div>
            </fieldset>
            <div className="grid gap-3 tablet:grid-cols-3">
              <Field id="br-gender" label="대상 성별(메모)">
                <select id="br-gender" className={INPUT} value={brief.gender} disabled={lock} onChange={(ev) => setB({ gender: ev.target.value as BriefDraft["gender"] })}>
                  <option value="">선택 안 함</option>
                  <option value="female">여성</option>
                  <option value="male">남성</option>
                  <option value="all">전체</option>
                </select>
              </Field>
              <Field id="br-age" label="대상 연령대(메모)">
                <input id="br-age" className={INPUT} value={brief.age} maxLength={100} disabled={lock} onChange={(ev) => setB({ age: ev.target.value })} />
              </Field>
              <Field id="br-keyword" label="댓글 유도 단어" hint="게시 문구의 고정 댓글 안내에 쓰입니다.">
                <input id="br-keyword" className={INPUT} value={keyword} maxLength={50} disabled={lock} onChange={(ev) => setKeyword(ev.target.value)} />
              </Field>
            </div>
          </>
        )}
      </section>

      <section aria-label="제휴 링크" className={cn(CARD, "flex flex-col gap-3")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-h2 font-bold">제휴 링크 ({affiliates.length}/20)</h2>
          <button type="button" className={SECONDARY} disabled={lock || affiliates.length >= 20} onClick={() => setAffiliates((a) => [...a, { lang: "ko", partner: "", url: "" }])}>
            ＋ 행
          </button>
        </div>
        <p className="text-caption text-text-muted">링크는 직접 입력합니다(자동 수집 없음). https 주소만, 게시 문구에만 쓰이고 영상에는 들어가지 않습니다.</p>
        {affiliates.length === 0 ? (
          <p className="text-body text-text-muted">제휴 링크가 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {affiliates.map((a, i) => (
              <li key={i} className="flex flex-col gap-2 rounded-card border border-border bg-bg p-3">
                <div className="grid gap-3 tablet:grid-cols-[6rem_1fr_2fr_auto] tablet:items-end">
                  <Field id={`af-${i}-lang`} label="언어">
                    <select id={`af-${i}-lang`} className={INPUT} value={a.lang} disabled={lock} onChange={(ev) => setAffiliates((l) => l.map((x, n) => (n === i ? { ...x, lang: ev.target.value as "ko" | "ja" } : x)))}>
                      <option value="ko">ko</option>
                      <option value="ja">ja</option>
                    </select>
                  </Field>
                  <Field id={`af-${i}-partner`} label="제휴처">
                    <input id={`af-${i}-partner`} className={INPUT} value={a.partner} maxLength={50} disabled={lock} onChange={(ev) => setAffiliates((l) => l.map((x, n) => (n === i ? { ...x, partner: ev.target.value } : x)))} />
                  </Field>
                  <Field id={`af-${i}-url`} label="URL(수동 입력)">
                    <input id={`af-${i}-url`} inputMode="url" className={INPUT} value={a.url} maxLength={2048} disabled={lock} onChange={(ev) => setAffiliates((l) => l.map((x, n) => (n === i ? { ...x, url: ev.target.value } : x)))} />
                  </Field>
                  <button type="button" className={SECONDARY} disabled={lock} onClick={() => setAffiliates((l) => l.filter((_, n) => n !== i))} aria-label={`제휴 링크 ${i + 1} 삭제`}>
                    삭제
                  </button>
                </div>
                {errors.affiliates?.[i] && (
                  <p role="alert" className="text-caption text-danger">
                    {errors.affiliates[i]}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {warnings.length > 0 && (
        <section aria-label="경고" className="rounded-panel border border-border bg-warning-soft p-4 text-body text-warning-soft-fg">
          <ul className="list-disc pl-5">
            {warnings.map((w) => (
              <li key={w.id}>{w.text}</li>
            ))}
          </ul>
        </section>
      )}

      {busy && (
        <p role="status" className="rounded-control bg-warning-soft px-3 py-2 text-body text-warning-soft-fg">
          {PHASE_LABEL[phase as Exclude<Phase, "idle">]}
        </p>
      )}
      {message && (
        <p role={message.tone === "error" ? "alert" : "status"} className={cn("rounded-control px-3 py-2 text-body", message.tone === "error" ? "bg-danger-soft text-danger-soft-fg" : "bg-success-soft text-success-soft-fg")}>
          {message.text}
        </p>
      )}

      <div className="fixed inset-x-0 bottom-0 z-10 flex flex-col gap-2 border-t border-border bg-surface p-3 tablet:static tablet:flex-row tablet:flex-wrap tablet:border-0 tablet:bg-transparent tablet:p-0">
        <button type="submit" disabled={lock} className={PRIMARY}>
          {failedPrepare ? "원본 준비 다시 시작" : "원본 준비 시작"}
        </button>
        <button type="button" disabled={lock} onClick={() => void submit("save")} className={SECONDARY}>
          저장
        </button>
        {ready ? (
          <Link href={`/production/${encodeURIComponent(job!.id)}/edit`} className={cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS)}>
            편집안으로
          </Link>
        ) : (
          <button type="button" disabled className={SECONDARY}>
            편집안으로
          </button>
        )}
        <Link href="/production" className={cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS)}>
          취소
        </Link>
        {preparing && <span className="self-center text-body text-text-muted">원본 준비 중</span>}
      </div>
    </form>
  );
}
