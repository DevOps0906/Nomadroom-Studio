import type { JobFormat } from "@/server/api/production";
import { defaultTts, type Tts } from "../edit/model";

// ja 탭 음성(녹음 업로드) 판단(순수). 서버 검증이 정본이고 여기는 spec 갱신·버튼 조건만 정한다.
// 근거: docs/04_API.md A-10(hook_audio·narration)·A-12(ja), docs/05_DATA_MODEL.md hook.audio_asset_id / voice.narration_asset_ids.

export const NARRATION_COUNT = 4;
export type VoiceMode = "tts" | "recording";
export type VoiceKind = "hook" | "narration";

export type VoiceDraft = {
  mode: VoiceMode;
  /** category 훅 음성(hook_audio 1개) */
  hookId: string | null;
  /** shopping 문장별 녹음(문장 순서, 4칸) */
  narrationIds: (string | null)[];
  /** TTS로 돌아갈 때 쓰는 값(원래 spec 값, 없으면 ja 기본 목소리) */
  tts: Tts;
};

/** 형식별 녹음 종류. variety는 녹음 업로드가 없다(hook_audio는 variety 400). */
export function voiceKind(format: JobFormat): VoiceKind | null {
  if (format === "category") return "hook";
  if (format === "shopping") return "narration";
  return null;
}

const obj = (v: unknown): Record<string, unknown> | null => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

function ttsOf(v: unknown): Tts {
  const o = obj(v);
  const voice = str(o?.voice);
  if (!o || !voice) return defaultTts("ja");
  const rate = str(o.rate);
  return rate ? { voice, rate } : { voice };
}

/** ja spec의 음성 상태. */
export function voiceOf(format: JobFormat, spec: Record<string, unknown>): VoiceDraft {
  const kind = voiceKind(format);
  const empty: (string | null)[] = Array.from({ length: NARRATION_COUNT }, () => null);
  if (kind === "hook") {
    const hook = obj(spec.hook);
    const id = str(hook?.audio_asset_id);
    return { mode: id ? "recording" : "tts", hookId: id, narrationIds: empty, tts: ttsOf(hook?.tts) };
  }
  if (kind === "narration") {
    const voice = obj(spec.voice);
    const ids = Array.isArray(voice?.narration_asset_ids) ? (voice.narration_asset_ids as unknown[]) : [];
    const has = ids.some((x) => typeof x === "string");
    return { mode: has ? "recording" : "tts", hookId: null, narrationIds: empty.map((_, i) => str(ids[i])), tts: ttsOf(voice?.tts) };
  }
  return { mode: "tts", hookId: null, narrationIds: empty, tts: defaultTts("ja") };
}

/** 녹음 모드에서 저장 가능한가(category 1개, shopping 서로 다른 4개). */
export function recordingComplete(format: JobFormat, d: VoiceDraft): boolean {
  const kind = voiceKind(format);
  if (kind === "hook") return !!d.hookId;
  if (kind === "narration") return d.narrationIds.every(Boolean) && new Set(d.narrationIds).size === NARRATION_COUNT;
  return false;
}

/** 저장 막는 사유(없으면 null). TTS 모드는 항상 저장 가능. */
export function voiceBlocker(format: JobFormat, d: VoiceDraft): string | null {
  if (d.mode !== "recording" || recordingComplete(format, d)) return null;
  return voiceKind(format) === "hook" ? "훅 녹음을 올려야 녹음 모드로 저장할 수 있습니다." : `문장별 녹음 ${NARRATION_COUNT}개를 모두(서로 다른 파일로) 올려야 녹음 모드로 저장할 수 있습니다.`;
}

/** 음성 상태를 spec 사본에 반영한다. 음성 밖 값은 건드리지 않는다. 녹음 모드는 TTS 값을 지우고 그 반대도 같다(둘 중 하나). */
export function applyVoice(format: JobFormat, spec: Record<string, unknown>, d: VoiceDraft): Record<string, unknown> {
  const kind = voiceKind(format);
  if (!kind) return spec;
  const next = JSON.parse(JSON.stringify(spec)) as Record<string, unknown>;
  const recording = d.mode === "recording";
  if (kind === "hook") {
    const hook = { ...(obj(next.hook) ?? {}) };
    delete hook.audio_asset_id;
    delete hook.tts;
    if (recording) hook.audio_asset_id = d.hookId;
    else hook.tts = d.tts;
    next.hook = hook;
  } else {
    next.voice = recording ? { narration_asset_ids: d.narrationIds.filter((x): x is string => !!x) } : { tts: d.tts };
  }
  return next;
}

/** 저장본과 화면 음성이 다른가. */
export function voiceDirty(format: JobFormat, spec: Record<string, unknown>, d: VoiceDraft): boolean {
  if (!voiceKind(format)) return false;
  return JSON.stringify(applyVoice(format, spec, voiceOf(format, spec))) !== JSON.stringify(applyVoice(format, spec, d));
}

/** 문장 i 칸에 업로드한 자산을 넣는다(녹음 모드로 전환). */
export function withNarration(d: VoiceDraft, index: number, assetId: string): VoiceDraft {
  return { ...d, mode: "recording", narrationIds: d.narrationIds.map((x, n) => (n === index ? assetId : x)) };
}

export const withHook = (d: VoiceDraft, assetId: string): VoiceDraft => ({ ...d, mode: "recording", hookId: assetId });
