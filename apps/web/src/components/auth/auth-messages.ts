export type AuthErrorKind = "credentials" | "rate_limited" | "unavailable";

export const AUTH_ERROR_MESSAGES: Record<AuthErrorKind, string> = {
  credentials: "이메일 또는 비밀번호가 일치하지 않습니다.",
  rate_limited: "시도가 너무 많습니다. 5분 뒤 다시 시도하세요.",
  unavailable: "일시적인 문제로 처리하지 못했습니다. 잠시 뒤 다시 시도하세요.",
};

export type LoginState = { error: AuthErrorKind | null; email: string };
