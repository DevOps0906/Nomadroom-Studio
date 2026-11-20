"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { EVIDENCE_SESSION_EXPIRED_PATH as SESSION_EXPIRED_PATH } from "@/components/evidence/evidence";
import type { JobFormat, RightsBasis } from "@/server/api/production";
import { AUDIO_ACCEPT, MAX_AUDIO_BYTES, audioMime, completeHookAudio, putAudio, requestHookAudio } from "../edit/api";
import { uploadAsset } from "../shopping/api";
import { ALL_BASES } from "../shopping/model";
import { BasisSelect } from "../shopping/ui";
import { NARRATION_COUNT, voiceBlocker, voiceKind, withHook, withNarration, type VoiceDraft } from "./voice-model";

// ja 탭 음성: 일본어 TTS ↔ 녹음 업로드 전환(JA-04). 업로드는 A-10 기존 흐름(hook_audio·narration)을 그대로 쓰고,
// 올린 자산은 저장(A-12 ja)할 때 ja spec에 들어간다. 상한·권한·상태는 서버 검증이 정본이다.

const FOCUS = "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
const INPUT = "min-h-11 w-full rounded-control border border-input bg-bg px-3 text-(length:--text-input) text-text outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const CARD = "rounded-panel border border-border bg-surface p-4 tablet:p-5";
const SHORT = (id: string | null) => (id ? id.slice(0, 8) : "없음");

export function VoicePanel({
  jobId,
  format,
  value,
  onChange,
  disabled,
  onError,
}: {
  jobId: string;
  format: JobFormat;
  value: VoiceDraft;
  onChange: (next: VoiceDraft) => void;
  disabled: boolean;
  onError: (message: string) => void;
}) {
  const kind = voiceKind(format);
  const [uploading, setUploading] = useState(false);
  const [basis, setBasis] = useState<"" | RightsBasis>("own");
  const [notice, setNotice] = useState<string | null>(null);
  if (!kind) return null;
  const lock = disabled || uploading;
  const blocker = voiceBlocker(format, value);

  function fail(status: number, message: string) {
    if (status === 401) return window.location.assign(SESSION_EXPIRED_PATH);
    onError(message);
  }

  async function uploadHook(file: File) {
    if (lock) return;
    const mime = audioMime(file);
    if (!mime) return onError("wav·mp3·m4a 파일만 올릴 수 있습니다.");
    if (file.size === 0 || file.size > MAX_AUDIO_BYTES) return onError("음성 파일은 50MB 이하여야 합니다.");
    setUploading(true);
    setNotice(null);
    const t = await requestHookAudio(jobId, file.size, mime);
    if (!t.ok) {
      setUploading(false);
      return fail(t.status, t.message);
    }
    if (!(await putAudio(t.data.upload_url, file, mime))) {
      setUploading(false);
      return onError("음성 업로드에 실패했습니다. 다시 시도하세요.");
    }
    const c = await completeHookAudio(jobId, t.data.asset.id);
    setUploading(false);
    if (!c.ok) return fail(c.status, c.message);
    onChange(withHook(value, t.data.asset.id));
    setNotice("훅 녹음을 올렸습니다. 저장하면 일본어판에 반영됩니다.");
  }

  async function uploadNarration(file: File, index: number) {
    if (lock) return;
    const mime = audioMime(file);
    if (!mime) return onError("wav·mp3·m4a 파일만 올릴 수 있습니다.");
    if (file.size === 0 || file.size > MAX_AUDIO_BYTES) return onError("음성 파일은 50MB 이하여야 합니다.");
    if (!basis) return onError("권리 근거를 먼저 선택하세요.");
    setUploading(true);
    setNotice(null);
    const r = await uploadAsset(jobId, file, "narration", mime, { basis });
    setUploading(false);
    if (!r.ok) return fail(r.status, r.message);
    onChange(withNarration(value, index, r.data.assetId));
    setNotice(`${index + 1}번 문장 녹음을 올렸습니다. 저장하면 일본어판에 반영됩니다.`);
  }

  return (
    <section aria-label="일본어판 음성" className={cn(CARD, "flex flex-col gap-3")}>
      <h2 className="text-h2 font-bold">음성</h2>
      <p className="text-body text-text-muted">ko 녹음은 쓸 수 없습니다. 일본어 TTS를 쓰거나 일본어 녹음을 새로 올리세요(둘 중 하나).</p>
      <fieldset className="flex flex-wrap gap-4" disabled={lock}>
        <legend className="sr-only">음성 방식</legend>
        <label className="inline-flex min-h-11 items-center gap-2 text-body">
          <input type="radio" name="ja-voice-mode" checked={value.mode === "tts"} onChange={() => onChange({ ...value, mode: "tts" })} />
          일본어 TTS
        </label>
        <label className="inline-flex min-h-11 items-center gap-2 text-body">
          <input type="radio" name="ja-voice-mode" checked={value.mode === "recording"} onChange={() => onChange({ ...value, mode: "recording" })} />
          녹음 업로드
        </label>
      </fieldset>

      {value.mode === "tts" && <p className="text-caption text-text-muted">대사·문구가 외부 음성 합성(TTS) 서비스로 전송됩니다. 목소리: {value.tts.voice}</p>}

      {value.mode === "recording" && kind === "hook" && (
        <div className="flex flex-col gap-1">
          <label htmlFor="ja-hook-file" className="text-body font-medium">
            훅 녹음 (wav·mp3·m4a, 50MB 이하)
          </label>
          <input id="ja-hook-file" type="file" accept={AUDIO_ACCEPT} disabled={lock} className={cn(INPUT, "py-2", FOCUS)} onChange={(e) => e.target.files?.[0] && void uploadHook(e.target.files[0])} />
          <p className="text-caption text-text-muted">현재 자산: {SHORT(value.hookId)}</p>
        </div>
      )}

      {value.mode === "recording" && kind === "narration" && (
        <div className="flex flex-col gap-3">
          <BasisSelect id="ja-narr-basis" value={basis} bases={ALL_BASES} disabled={lock} onChange={setBasis} />
          <p className="text-caption text-text-muted">
            문장별 녹음 {value.narrationIds.filter(Boolean).length}/{NARRATION_COUNT} · wav·mp3·m4a 50MB 이하. 문장 i의 자막 구간은 녹음 i의 실제 길이로 정해집니다.
          </p>
          {value.narrationIds.map((nid, i) => (
            <div key={i} className="flex flex-col gap-1">
              <label htmlFor={`ja-nr-${i}-file`} className="text-body font-medium">
                {i + 1}번 문장 녹음 (현재: {SHORT(nid)})
              </label>
              <input id={`ja-nr-${i}-file`} type="file" accept={AUDIO_ACCEPT} disabled={lock} className={cn(INPUT, "py-2", FOCUS)} onChange={(e) => e.target.files?.[0] && void uploadNarration(e.target.files[0], i)} />
            </div>
          ))}
        </div>
      )}

      {uploading && <p role="status" className="text-body text-text-muted">업로드 중…</p>}
      {blocker && <p role="status" className="text-caption text-warning">{blocker}</p>}
      {notice && <p role="status" className="text-body text-success">{notice}</p>}
    </section>
  );
}
