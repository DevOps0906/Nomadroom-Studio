"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { AUTH_ERROR_MESSAGES } from "@/components/auth/auth-messages";
import { AuthAlert, AuthField, AuthLink, SubmitButton } from "@/components/auth/auth-ui";
import { requestPasswordReset, type ForgotState } from "./actions";

const INITIAL: ForgotState = { sent: false, error: null, email: "" };

function Body({ state, linkError }: { state: ForgotState; linkError: boolean }) {
  const { pending } = useFormStatus();
  const showLinkError = linkError && !state.sent && !state.error;
  const errorId = state.error || showLinkError ? "forgot-error" : undefined;
  return (
    <div className="grid gap-4">
      {showLinkError && <AuthAlert tone="danger" id="forgot-error">재설정 링크가 만료되었거나 올바르지 않습니다. 다시 요청하세요.</AuthAlert>}
      {state.error && <AuthAlert tone="danger" id="forgot-error">{AUTH_ERROR_MESSAGES[state.error]}</AuthAlert>}
      {state.sent && <AuthAlert tone="success">입력한 이메일이 등록되어 있다면 재설정 링크를 보냈습니다. 메일함을 확인하세요.</AuthAlert>}
      <AuthField label="이메일" id="email" name="email" type="email" autoComplete="email" required defaultValue={state.email} aria-invalid={!!state.error || undefined} aria-describedby={errorId} />
      <SubmitButton pending={pending}>{pending ? "보내는 중" : "재설정 링크 보내기"}</SubmitButton>
      <AuthLink href="/login">로그인으로 돌아가기</AuthLink>
    </div>
  );
}

export function ForgotForm({ linkError }: { linkError: boolean }) {
  const [state, action] = useActionState(requestPasswordReset, INITIAL);
  return (
    <form action={action}>
      <Body state={state} linkError={linkError} />
    </form>
  );
}
