"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { AuthAlert, AuthField, SubmitButton } from "@/components/auth/auth-ui";
import { resetPassword, type ResetState } from "./actions";

const INITIAL: ResetState = { error: null };

function Body({ state }: { state: ResetState }) {
  const { pending } = useFormStatus();
  const invalid = !!state.error || undefined;
  const errorId = state.error ? "reset-error" : undefined;
  return (
    <div className="grid gap-4">
      {state.error && <AuthAlert tone="danger" id="reset-error">{state.error}</AuthAlert>}
      <AuthField label="새 비밀번호" id="password" name="password" type="password" autoComplete="new-password" required aria-invalid={invalid} aria-describedby={errorId} />
      <AuthField label="새 비밀번호 확인" id="confirm" name="confirm" type="password" autoComplete="new-password" required aria-invalid={invalid} aria-describedby={errorId} />
      <SubmitButton pending={pending}>{pending ? "변경 중" : "비밀번호 변경"}</SubmitButton>
    </div>
  );
}

export function ResetForm() {
  const [state, action] = useActionState(resetPassword, INITIAL);
  return (
    <form action={action}>
      <Body state={state} />
    </form>
  );
}
