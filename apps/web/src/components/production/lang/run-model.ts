// PROD-03 ja 탭 판단(순수). 서버가 정본이고 여기는 버튼 노출·안내 문구만 정한다.

import type { ProductionJobDetail, ProductionAsset, RunSummary } from "@/server/api/production";
import type { Lang } from "./model";

export type JaRunState = { canRequest: boolean; message: string };

export function jaRunState(ja: { approved_at: string | null } | null): JaRunState {
  if (!ja) return { canRequest: false, message: "일본어판이 아직 없습니다. 편집안의 ja 탭에서 \"일본어판 만들기\"로 시작하세요." };
  if (!ja.approved_at) return { canRequest: false, message: "일본어판이 아직 승인되지 않았습니다. 편집안의 ja 탭에서 수정·승인하세요." };
  return { canRequest: true, message: "승인됨 — 렌더 요청을 눌러 시작(ko와 별도 렌더입니다)" };
}

export const TTS_DISCLOSURE = "대사·문구가 외부 음성 합성(TTS) 서비스로 전송됩니다.";

// ---- 언어별 run·산출물 선택(task-060, A-09 latest_runs·assets[].render_lang) ----

/** 언어별 최신 run. 구 API(latest_runs 없음)는 ko만 latest_run으로 본다. */
export function runOfLang(d: Pick<ProductionJobDetail, "latest_run" | "latest_runs">, lang: Lang): RunSummary | null {
  if (d.latest_runs) return d.latest_runs[lang];
  return lang === "ko" ? d.latest_run : null;
}

/** render_lang이 이 언어로 확인된 산출물인가. null(run 미확인)은 어느 언어로도 단정하지 않는다. 구 API(필드 없음)만 ko로 본다. */
const isLang = (a: ProductionAsset, lang: Lang) => (lang === "ja" ? a.render_lang === "ja" : a.render_lang === "ko" || a.render_lang === undefined);

/** 언어별 가장 최근 ready 산출물(자산은 생성 순). */
export function assetOfLang(assets: ProductionAsset[], kind: "output_mp4" | "report", lang: Lang): string | null {
  const ready = assets.filter((a) => a.kind === kind && a.status === "ready" && isLang(a, lang));
  return ready.length ? ready[ready.length - 1].id : null;
}

/** ko 탭 화면용: latest_run을 ko run으로, 렌더 산출물(mp4·리포트)은 ko로 확인된 것만 남긴다(원본·시트 등은 그대로). */
export function koDetail(d: ProductionJobDetail): ProductionJobDetail {
  return { ...d, latest_run: runOfLang(d, "ko"), assets: d.assets.filter((a) => (a.kind !== "output_mp4" && a.kind !== "report") || isLang(a, "ko")) };
}
