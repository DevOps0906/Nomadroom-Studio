import { isUuid } from "@/components/monitoring/query";
import { SourceForm, type CandidateInfo } from "@/components/production/source-form";
import { CandidateCard, SourceHeader } from "@/components/production/source-view";

export const metadata = { title: "새 제작 작업 · Nomadroom Studio" };

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

/** PROD-01 첫 입력(작업 만들기 전). MON-01 "내부 제작"에서 후보 ID·제목·라이선스를 쿼리로 받는다. */
export default async function NewProductionPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const id = one(sp.candidate_id);
  const title = one(sp.title)?.trim().slice(0, 200);
  const license = one(sp.license);
  const candidate: CandidateInfo | null =
    isUuid(id) && title ? { id: id.toLowerCase(), title, license_cc: license === "cc" ? true : license === "other" ? false : null } : null;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5">
      <SourceHeader title="새 제작 작업" />
      {candidate && <CandidateCard candidate={candidate} />}
      <SourceForm job={null} candidate={candidate} hasReadySource={false} initialFormat={one(sp.format) === "variety" ? "variety" : "category"} />
    </div>
  );
}
