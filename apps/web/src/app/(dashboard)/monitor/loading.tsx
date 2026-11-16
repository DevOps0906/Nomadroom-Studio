import { CandidateSkeleton, ProgressSkeleton } from "@/components/monitoring/monitor-view";

const BTN = "inline-flex min-h-11 items-center justify-center rounded-control px-4 text-body font-semibold opacity-55";

/** 로딩: 두 실행 버튼 비활성 + 프로필별 진행 자리 + 카드 스켈레톤. 라벨은 "후보 가져오는 중"으로 통일. */
export default function MonitorLoading() {
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 tablet:gap-5">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
        <h1 className="text-h1 font-bold">소재수집(정체)</h1>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled className={`${BTN} border border-border bg-surface text-text`}>
            후보 가져오기
          </button>
          <button type="button" disabled className={`${BTN} bg-primary text-primary-fg`}>
            기록 검증 실행
          </button>
        </div>
      </div>
      <ProgressSkeleton />
      <CandidateSkeleton label="후보 가져오는 중" />
    </div>
  );
}
