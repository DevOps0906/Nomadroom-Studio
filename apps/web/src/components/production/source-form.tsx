"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import { createIntentKey } from "@/components/monitoring/intent-key";
import type { ProductionStatus } from "@/server/api/production";
import { completeUpload, createJob, type JobFormat, isYoutubeUrl, patchJob, prepareJob, putFile, requestUpload, type Result } from "./api";

export { isYoutubeUrl };
import { FILE_ACCEPT, MAX_FILE_BYTES, STAGE_LABEL, STATUS_LABEL, STATUS_TONE, formatBytes, mimeOf, validateSource, type SourceErrors } from "./format";

// PROD-01 원본·구간·출처 폼. 순서: (생성 | 저장) → 업로드(서명 PUT) → 완료 확인 → 준비 시작(A-11).
// 근거: docs/03_SCREENS_UX.md PROD-01, tasks/task-025.md. 형식 선택(카테고리형·예능형, 작업 생성 뒤 잠금).

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const INPUT =
  "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-55";
const PRIMARY = cn(BTN, "bg-primary text-primary-fg hover:bg-primary-hover", FOCUS);
const SECONDARY = cn(BTN, "border border-border bg-surface text-text hover:bg-surface-alt", FOCUS);

export type SourceJob = {
  id: string;
  title: string;
  status: ProductionStatus;
  failed_stage: "prepare" | "audio" | "render" | null;
  error_code: string | null;
  rights_confirmed: boolean;
  license_cc: boolean | null;
  credit: string | null;
  source_start_sec: number;
  segment_len_sec: number;
  source_kind?: "upload" | "url";
  source_url?: string | null;
  format?: JobFormat;
};

export type CandidateInfo = { id: string; title: string; license_cc: boolean | null };
type Phase = "idle" | "saving" | "uploading" | "confirming" | "preparing";
type License = "unknown" | "cc" | "other";
type SourceKind = "upload" | "url";
type FormErrors = SourceErrors & { url?: string };

const LICENSE_LABEL: Record<License, string> = { unknown: "미확인", cc: "CC(재사용 허용)", other: "그 외" };
const PHASE_LABEL: Record<Exclude<Phase, "idle">, string> = {
  saving: "저장하는 중…",
  uploading: "원본 업로드 중…",
  confirming: "업로드 확인 중…",
  preparing: "원본 준비를 시작하는 중…",
};
const toLicense = (cc: boolean | null): License => (cc === null ? "unknown" : cc ? "cc" : "other");
const fromLicense = (l: License): boolean | null => (l === "unknown" ? null : l === "cc");

export function isEditable(job: Pick<SourceJob, "status" | "failed_stage"> | null): boolean {
  return !job || job.status === "draft" || (job.status === "failed" && job.failed_stage === "prepare");
}

function Field({ id, label, required, hint, error, children }: { id: string; label: string; required?: boolean; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-body font-medium text-text">
        {label}
        {required && (
          <span aria-hidden className="text-danger">
            {" "}
            *
          </span>
        )}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-caption text-text-muted">
          {hint}
        </p>
      )}
      <p id={`${id}-err`} role={error ? "alert" : undefined} className="text-caption text-danger">
        {error}
      </p>
    </div>
  );
}

export function SourceForm({
  job,
  candidate,
  hasReadySource,
  readySourceInfo,
  initialFormat = "category",
}: {
  job: SourceJob | null;
  candidate: CandidateInfo | null;
  hasReadySource: boolean;
  readySourceInfo?: string;
  initialFormat?: JobFormat;
}) {
  const router = useRouter();
  const editable = isEditable(job);
  const preparing = job?.status === "preparing";
  const ready = !!job && ["review", "rendering", "inspect", "done"].includes(job.status);

  const [format, setFormat] = useState<JobFormat>(job?.format ?? initialFormat);
  const [title, setTitle] = useState(job?.title ?? candidate?.title ?? "");
  const [start, setStart] = useState(String(job?.source_start_sec ?? 0));
  const [len, setLen] = useState(String(job?.segment_len_sec ?? 30));
  const [rights, setRights] = useState(job?.rights_confirmed ?? false);
  const [license, setLicense] = useState<License>(toLicense(job?.license_cc ?? candidate?.license_cc ?? null));
  const [credit, setCredit] = useState(job?.credit ?? "");
  const [file, setFile] = useState<File | null>(null);
  // URL 받기 실패(url_unavailable)면 파일 업로드로 전환해 보여준다(PROD-01 오류 상태).
  const [kind, setKind] = useState<SourceKind>(job?.error_code === "url_unavailable" ? "upload" : (job?.source_kind ?? "upload"));
  const [url, setUrl] = useState(job?.source_url ?? "");
  const [errors, setErrors] = useState<FormErrors>({});
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const busy = phase !== "idle";

  const createdId = useRef<string | null>(null);
  const [created, setCreated] = useState(false);
  const titleLocked = !!job || created;
  const formatLocked = !!job || created; // 작업 생성 뒤에는 서버가 형식 변경을 받지 않는다(원본 준비 시작 후 잠금 포함)
  const intent = useRef(createIntentKey());

  // 원본 준비 중이면 상태를 주기적으로 다시 읽는다.
  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [preparing, router]);

  function fail<T>(r: Extract<Result<T>, { ok: false }>) {
    if (r.status === 401) {
      window.location.assign(SESSION_EXPIRED_PATH);
      return;
    }
    if (r.field === "source_url") setErrors((e) => ({ ...e, url: r.message }));
    if (r.field === "title" || r.field === "segment_len_sec" || r.field === "rights_confirmed") {
      const key = r.field === "title" ? "title" : r.field === "rights_confirmed" ? "rights" : "len";
      setErrors((e) => ({ ...e, [key]: r.message }));
    }
    setMessage({ tone: "error", text: r.message });
    setPhase("idle");
  }

  async function submit(mode: "save" | "start") {
    if (busy || !editable) return;
    setMessage(null);
    const useUrl = kind === "url";
    const errs: FormErrors = validateSource({ title, start, len, rights, hasFile: useUrl || !!file, hasReadySource }, mode === "start");
    if (useUrl && !isYoutubeUrl(url)) errs.url = "YouTube 주소(https)만 입력할 수 있습니다.";
    if (!useUrl && file) {
      if (!mimeOf(file)) errs.file = "mp4·mov·webm·mkv 파일만 올릴 수 있습니다.";
      else if (file.size > MAX_FILE_BYTES) errs.file = "파일 크기는 500MB 이하여야 합니다.";
      else if (file.size === 0) errs.file = "빈 파일입니다.";
    }
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    const values = {
      rights_confirmed: rights,
      license_cc: fromLicense(license),
      credit: credit.trim() || null,
      source_start_sec: Number(start),
      segment_len_sec: Number(len),
      source_kind: kind,
      source_url: useUrl ? url.trim() : null,
    };
    setPhase("saving");
    let id = job?.id ?? createdId.current;
    if (!id) {
      const body = { ...values, title: title.trim(), ...(candidate ? { candidate_id: candidate.id } : {}) };
      const r = await createJob(body, intent.current.current(JSON.stringify({ ...body, format })), undefined, format);
      intent.current.settle(!r.ok && r.keepKey);
      if (!r.ok) return fail(r);
      id = createdId.current = r.data.job.id;
      setCreated(true);
    } else {
      const r = await patchJob(id, values);
      if (!r.ok) return fail(r);
    }

    if (mode === "start") {
      if (!useUrl && file) {
        const mime = mimeOf(file)!;
        const t = await requestUpload(id, file.size, mime);
        if (!t.ok) return fail(t);
        setPhase("uploading");
        if (!(await putFile(t.data.upload_url, file, mime))) {
          setMessage({ tone: "error", text: "원본 업로드에 실패했습니다. 다시 시도하세요." });
          return setPhase("idle");
        }
        setPhase("confirming");
        const c = await completeUpload(id, t.data.asset.id);
        if (!c.ok) return fail(c);
      }
      setPhase("preparing");
      const p = await prepareJob(id);
      if (!p.ok) return fail(p);
    }

    setPhase("idle");
    setFile(null);
    if (job) {
      setMessage({ tone: "ok", text: mode === "save" ? "저장했습니다." : "원본 준비를 시작했습니다." });
      router.refresh();
    } else {
      router.replace(`/production/${encodeURIComponent(id)}/source`);
    }
  }

  const lock = !editable || busy;
  const failedPrepare = job?.status === "failed" && job.failed_stage === "prepare";
  const urlFailed = failedPrepare && job?.error_code === "url_unavailable";

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit("start");
      }}
      className="flex flex-col gap-4"
      aria-busy={busy}
    >
      <section className="flex flex-col gap-4 rounded-panel border border-border bg-surface p-4 tablet:p-5">
        {job && (
          <div className="flex flex-wrap items-center gap-2" aria-live="polite">
            <span className={cn("rounded-chip px-2 py-0.5 text-caption font-semibold", STATUS_TONE[job.status])}>{STATUS_LABEL[job.status]}</span>
            {preparing && <span className="text-body text-text-muted">원본 준비 중</span>}
            {failedPrepare && (
              <span className="text-body text-danger" role="alert">
                {urlFailed
                  ? "URL에서 원본을 받지 못했습니다(권한·접근 제한·네트워크). 파일을 업로드해 진행하세요."
                  : `${STAGE_LABEL.prepare} 단계 실패${job.error_code ? ` (${job.error_code})` : ""}. 다시 시작할 수 있습니다.`}
              </span>
            )}
            {job.status === "failed" && !failedPrepare && (
              <span className="text-body text-danger" role="alert">
                {job.failed_stage ? STAGE_LABEL[job.failed_stage] : "작업"} 단계 실패{job.error_code ? ` (${job.error_code})` : ""}
              </span>
            )}
          </div>
        )}

        <Field id="src-format" label="형식" required hint={formatLocked ? "형식은 바꿀 수 없음" : undefined}>
          <select id="src-format" className={INPUT} disabled={formatLocked || lock} value={format} onChange={(e) => setFormat(e.target.value as JobFormat)}>
            <option value="category">카테고리형</option>
            <option value="variety">예능형</option>
          </select>
        </Field>

        <Field id="src-title" label="제목" required hint={titleLocked ? "제목은 생성 후 바꿀 수 없습니다" : undefined} error={errors.title}>
          <input id="src-title" className={INPUT} value={title} maxLength={200} disabled={lock} readOnly={titleLocked} onChange={(e) => setTitle(e.target.value)} aria-invalid={!!errors.title} aria-describedby="src-title-hint src-title-err" />
        </Field>

        <Field
          id="src-file"
          label="원본 파일 업로드"
          required={!hasReadySource}
          hint={hasReadySource ? `업로드된 원본이 있습니다${readySourceInfo ? ` (${readySourceInfo})` : ""}. 새 파일은 선택하지 않아도 됩니다.` : "mp4·mov·webm·mkv, 500MB 이하"}
          error={errors.file}
        >
          <input
            id="src-file"
            type="file"
            accept={FILE_ACCEPT}
            disabled={lock || hasReadySource || kind === "url"}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            aria-invalid={!!errors.file}
            aria-describedby="src-file-hint src-file-err"
            className={cn(INPUT, "py-2")}
          />
          {file && <p className="text-caption text-text-muted">{file.name} · {formatBytes(file.size)}</p>}
        </Field>

        <div className="flex items-start gap-2">
          <input id="src-rights" type="checkbox" checked={rights} disabled={lock} onChange={(e) => setRights(e.target.checked)} className="mt-1 size-5 accent-primary" aria-describedby="src-rights-err" aria-invalid={!!errors.rights} />
          <div className="flex flex-col gap-1">
            <label htmlFor="src-rights" className="text-body font-medium text-text">
              사용 권한 확인 <span aria-hidden className="text-danger">*</span>
            </label>
            <p className="text-caption text-text-muted">이 원본을 편집·게시할 권리가 있음을 확인합니다.</p>
            <p id="src-rights-err" role={errors.rights ? "alert" : undefined} className="text-caption text-danger">
              {errors.rights}
            </p>
          </div>
        </div>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-body font-medium text-text">원본 방식</legend>
          <div className="flex flex-wrap gap-4">
            {(["upload", "url"] as const).map((k) => (
              <label key={k} className="flex min-h-11 items-center gap-2 text-body text-text">
                <input type="radio" name="src-kind" value={k} checked={kind === k} disabled={lock} onChange={() => setKind(k)} className="size-5 accent-primary" />
                {k === "upload" ? "파일 업로드" : "YouTube URL"}
              </label>
            ))}
          </div>
        </fieldset>
        {kind === "url" && (
          <Field id="src-url" label="원본 URL" required hint={rights ? "YouTube 주소만(로그인·쿠키가 필요한 영상은 받을 수 없습니다). 받지 못하면 파일 업로드로 진행하세요." : "사용 권한 확인 후 입력할 수 있습니다."} error={errors.url}>
            <input id="src-url" type="url" inputMode="url" className={INPUT} value={url} maxLength={2048} disabled={lock || !rights} onChange={(e) => setUrl(e.target.value)} aria-invalid={!!errors.url} aria-describedby="src-url-hint src-url-err" placeholder="https://www.youtube.com/watch?v=…" />
          </Field>
        )}

        <div className="grid gap-4 tablet:grid-cols-2">
          <Field id="src-start" label="원본 시작(초)" required error={errors.start}>
            <input id="src-start" inputMode="decimal" className={INPUT} value={start} disabled={lock} onChange={(e) => setStart(e.target.value)} aria-invalid={!!errors.start} aria-describedby="src-start-err" />
          </Field>
          <Field id="src-len" label="길이(초)" required hint="0 초과 180 이하" error={errors.len}>
            <input id="src-len" inputMode="decimal" className={INPUT} value={len} disabled={lock} onChange={(e) => setLen(e.target.value)} aria-invalid={!!errors.len} aria-describedby="src-len-hint src-len-err" />
          </Field>
          <Field id="src-credit" label="저작자">
            <input id="src-credit" className={INPUT} value={credit} maxLength={200} disabled={lock} onChange={(e) => setCredit(e.target.value)} />
          </Field>
          <Field id="src-license" label="라이선스">
            <select id="src-license" className={INPUT} value={license} disabled={lock} onChange={(e) => setLicense(e.target.value as License)}>
              {(Object.keys(LICENSE_LABEL) as License[]).map((k) => (
                <option key={k} value={k}>
                  {LICENSE_LABEL[k]}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </section>

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

      <div className="flex flex-col gap-2 tablet:flex-row tablet:flex-wrap">
        <button type="submit" disabled={lock} className={PRIMARY}>
          {failedPrepare ? "원본 준비 다시 시작" : "원본 준비 시작"}
        </button>
        <button type="button" disabled={lock} onClick={() => void submit("save")} className={SECONDARY}>
          저장
        </button>
        {ready ? (
          <Link href={`/production/${encodeURIComponent(job!.id)}/edit`} className={SECONDARY}>
            편집안으로
          </Link>
        ) : (
          <button type="button" disabled className={SECONDARY} aria-describedby={preparing ? "src-wait" : undefined}>
            편집안으로
          </button>
        )}
        <Link href="/production" className={SECONDARY}>
          취소
        </Link>
        {preparing && (
          <span id="src-wait" className="self-center text-body text-text-muted">
            원본 준비 중
          </span>
        )}
      </div>
    </form>
  );
}
