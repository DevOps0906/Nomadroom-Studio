"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { X } from "lucide-react";
import { toInput, validateConditions, type ConditionsInput, type FieldErrors, type Profile, type SaveResult } from "./conditions";
import { ConditionsFormView, FOCUS, type FormStatus } from "./conditions-form-view";

export type SaveConditionsAction = (id: string, updatedAt: string, input: ConditionsInput) => Promise<SaveResult>;

type Props = {
  profile: Profile;
  save: SaveConditionsAction;
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
};

/** MON-D1 조건 설정 모달. 오류가 나도 입력은 그대로 둔다. */
export function ConditionsDialog({ profile, save, onClose, onSaved, onRefresh }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [input, setInput] = useState<ConditionsInput>(() => toInput(profile));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<FormStatus>({ kind: "idle" });
  const [pending, startTransition] = useTransition();
  const titleId = `conditions-title-${profile.id}`;

  useEffect(() => {
    const el = ref.current;
    if (el && !el.open) el.showModal();
  }, []);

  // 오류가 생기면(검증·서버 400) 첫 오류 필드로 포커스를 옮긴다.
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [errors]);

  const shown: FormStatus = pending ? { kind: "saving" } : status;

  function submit() {
    const { payload, errors: found } = validateConditions(input, profile.updated_at);
    setErrors(found);
    if (!payload) {
      setStatus({ kind: "idle" });
      return;
    }
    startTransition(async () => {
      const res = await save(profile.id, profile.updated_at, input);
      if (res.ok) {
        setStatus({ kind: "idle" });
        onSaved();
        return;
      }
      if (res.kind === "field") {
        setErrors(res.errors);
        setStatus({ kind: "idle" });
      } else {
        setStatus({ kind: res.kind, message: res.message });
      }
    });
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        if (pending) e.preventDefault();
      }}
      onClose={onClose}
      className="m-auto max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-dialog border border-border bg-surface p-0 text-text shadow-card backdrop:bg-text/40"
    >
      <div className="p-5 tablet:p-6">
        <header className="mb-4 flex items-center justify-between gap-2">
          <h2 id={titleId} className="text-h2 font-bold">
            {profile.name} 조건 설정
          </h2>
          <button
            type="button"
            aria-label="닫기"
            disabled={pending}
            onClick={() => ref.current?.close()}
            className={`inline-flex size-11 items-center justify-center rounded-control text-text-muted hover:bg-surface-alt ${FOCUS}`}
          >
            <X aria-hidden className="size-5" />
          </button>
        </header>
        <ConditionsFormView
          formId={`conditions-${profile.id}`}
          input={input}
          errors={errors}
          status={shown}
          onChange={(patch) => setInput((prev) => ({ ...prev, ...patch }))}
          onSubmit={submit}
          onCancel={() => ref.current?.close()}
          onRefresh={onRefresh}
        />
      </div>
    </dialog>
  );
}
