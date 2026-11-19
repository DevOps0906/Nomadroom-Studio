import { cn } from "@/lib/utils";
import { itemSegments, shotSegments, type Draft } from "./model";

// 구간 타임라인 바: 구도(윗줄)·자막(아랫줄). 공백·겹침·순서 오류는 빨강, 1.4초 미만 자막은 노랑. 표시용이며 승인은 서버 검증이 정한다.

function Lane({ label, segs }: { label: string; segs: { left: number; width: number; bad: boolean; short: boolean }[] }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 shrink-0 text-caption text-text-muted">{label}</span>
      <div className="relative h-6 grow overflow-hidden rounded-control bg-neutral-soft">
        {segs.map((s, i) => (
          <span
            key={i}
            title={`${label} ${i + 1}`}
            style={{ left: `${s.left}%`, width: `${Math.max(s.width, 0.5)}%` }}
            className={cn("absolute inset-y-0 border-x border-surface", s.bad ? "bg-danger" : s.short ? "bg-warning" : "bg-primary")}
          />
        ))}
      </div>
    </div>
  );
}

export function Timeline({ draft, duration }: { draft: Draft; duration: number }) {
  if (!(duration > 0)) {
    return <p className="text-body text-text-muted">길이(초)를 입력하면 구간 타임라인이 표시됩니다.</p>;
  }
  const shots = shotSegments(draft.shots, duration);
  const items = itemSegments(draft.items, duration);
  const bad = shots.some((s) => s.bad) || items.some((s) => s.bad);
  return (
    <div className="flex flex-col gap-2" role="img" aria-label={bad ? "구간 타임라인: 공백 또는 겹침이 있습니다" : "구간 타임라인"}>
      <Lane label="구도" segs={shots} />
      <Lane label="자막" segs={items} />
      <p className="text-caption text-text-muted">
        <span className="text-danger">빨강</span> 공백·겹침 · <span className="text-warning">노랑</span> 1.4초 미만 · 전체 {duration}초
      </p>
    </div>
  );
}
