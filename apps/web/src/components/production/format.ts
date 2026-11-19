import type { ProductionStatus } from "@/server/api/production";

// PROD-00·PROD-01 공용 문구·검증(순수). 근거: docs/03_SCREENS_UX.md PROD-00·PROD-01, tasks/task-025.md.

export const STATUS_LABEL: Record<ProductionStatus, string> = {
  draft: "초안",
  preparing: "원본 준비",
  review: "편집안 검토",
  rendering: "렌더링",
  inspect: "검수 대기",
  done: "완료",
  failed: "실패",
};

export const STATUS_TONE: Record<ProductionStatus, string> = {
  draft: "bg-neutral-soft text-neutral-soft-fg",
  preparing: "bg-warning-soft text-warning-soft-fg",
  review: "bg-primary-soft text-primary-soft-fg",
  rendering: "bg-warning-soft text-warning-soft-fg",
  inspect: "bg-primary-soft text-primary-soft-fg",
  done: "bg-success-soft text-success-soft-fg",
  failed: "bg-danger-soft text-danger-soft-fg",
};

export const STATUS_FILTERS: { value: ProductionStatus | null; label: string }[] = [
  { value: null, label: "전체" },
  { value: "draft", label: STATUS_LABEL.draft },
  { value: "preparing", label: STATUS_LABEL.preparing },
  { value: "review", label: STATUS_LABEL.review },
  { value: "rendering", label: STATUS_LABEL.rendering },
  { value: "inspect", label: STATUS_LABEL.inspect },
  { value: "done", label: STATUS_LABEL.done },
  { value: "failed", label: STATUS_LABEL.failed },
];

const STATUS_SET = new Set<string>(Object.keys(STATUS_LABEL));
export function parseStatus(v: string | string[] | undefined): ProductionStatus | null {
  return typeof v === "string" && STATUS_SET.has(v) ? (v as ProductionStatus) : null;
}

export const LIST_PAGE_SIZE = 20;
export function parsePage(v: string | string[] | undefined): number {
  const n = typeof v === "string" && /^\d{1,3}$/.test(v) ? Number(v) : 1;
  return n >= 1 ? n : 1;
}

export const STAGE_LABEL = { prepare: "원본 준비", audio: "음성", render: "렌더" } as const;

/** 파일 확장자 → mime(서버 허용 목록: mp4·mov·webm·mkv). 브라우저가 mime을 비워 보내는 mkv 등을 보정한다. */
const MIME_BY_EXT: Record<string, string> = {
  mp4: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  mkv: "video/x-matroska",
};
export const FILE_ACCEPT = ".mp4,.mov,.webm,.mkv";
export const MAX_FILE_BYTES = 500 * 1024 * 1024;

export function mimeOf(file: { name: string; type: string }): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return MIME_BY_EXT[ext] ?? null;
}

export function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
  return `${Math.max(1, Math.round(n / 1024))}KB`;
}

export type SourceInput = { title: string; start: string; len: string; rights: boolean; hasFile: boolean; hasReadySource: boolean };
export type SourceErrors = Partial<Record<"title" | "start" | "len" | "rights" | "file", string>>;

const toNum = (s: string) => (s.trim() === "" ? NaN : Number(s));

export function validateSource(v: SourceInput, requireSource: boolean): SourceErrors {
  const e: SourceErrors = {};
  const title = v.title.trim();
  if (title.length < 1 || title.length > 200) e.title = "제목은 1~200자로 입력하세요.";
  const start = toNum(v.start);
  if (!Number.isFinite(start) || start < 0) e.start = "0 이상의 숫자를 입력하세요.";
  const len = toNum(v.len);
  if (!Number.isFinite(len) || len <= 0 || len > 180) e.len = "0 초과 180 이하의 숫자를 입력하세요.";
  if (!v.rights) e.rights = "사용 권한을 확인해야 합니다.";
  if (requireSource && !v.hasFile && !v.hasReadySource) e.file = "원본 파일을 선택하세요.";
  return e;
}

/** MON-01 → PROD-01 쿼리(후보 ID·제목·라이선스). 값은 비신뢰 입력이라 길이·형식을 제한한다. */
export function candidateHref(c: { id: string; title: string; license_cc: boolean | null }): string {
  const q = new URLSearchParams({ candidate_id: c.id, title: c.title.slice(0, 200) });
  if (c.license_cc !== null) q.set("license", c.license_cc ? "cc" : "other");
  return `/production/new?${q.toString()}`;
}
