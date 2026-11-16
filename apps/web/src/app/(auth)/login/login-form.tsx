"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { LoginFormView } from "@/components/auth/login-form-view";
import type { LoginState } from "@/components/auth/auth-messages";
import { login } from "./actions";

const INITIAL: LoginState = { error: null, email: "" };

function Body({ state, next, notice }: { state: LoginState; next: string; notice?: string }) {
  const { pending } = useFormStatus();
  return <LoginFormView pending={pending} error={state.error} email={state.email} next={next} notice={notice} />;
}

export function LoginForm({ next, notice }: { next: string; notice?: string }) {
  const [state, action] = useActionState(login, INITIAL);
  return (
    <form action={action}>
      <Body state={state} next={next} notice={notice} />
    </form>
  );
}
