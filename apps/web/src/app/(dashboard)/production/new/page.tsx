import { isUuid } from "@/components/monitoring/query";
import { SourceForm, type CandidateInfo } from "@/components/production/source-form";
import { CandidateCard, SourceHeader } from "@/components/production/source-view";
import { ShoppingSourceForm } from "@/components/production/shopping/source-form";
import { TypeChooser } from "@/components/production/type-chooser";

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

  // PROD-00 제작 시작: 후보·형식·유형 쿼리 없이 들어오면 유형부터 고른다(MON-01 후보는 일반 PROD-01로 바로).
  const kind = one(sp.kind);
  const vertical = one(sp.vertical);
  if (kind === "shopping" && (vertical === "product" || vertical === "travel")) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5 desktop:max-w-5xl">
        <SourceHeader title="새 쇼핑 제작 작업" />
        <ShoppingSourceForm job={null} assets={[]} initialVertical={vertical} />
      </div>
    );
  }
  if (!candidate && kind !== "general" && one(sp.format) === undefined) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5">
        <SourceHeader title="제작 시작" />
        <TypeChooser />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 tablet:gap-5">
      <SourceHeader title="새 제작 작업" />
      {candidate && <CandidateCard candidate={candidate} />}
      <SourceForm job={null} candidate={candidate} hasReadySource={false} initialFormat={one(sp.format) === "variety" ? "variety" : "category"} />
    </div>
  );
}
