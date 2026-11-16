import { AUTH_ERROR_MESSAGES, type AuthErrorKind } from "./auth-messages";
import { AuthAlert, AuthField, AuthLink, SubmitButton } from "./auth-ui";

const ERROR_ID = "login-error";

type Props = { pending: boolean; error: AuthErrorKind | null; email: string; next: string; notice?: string };

/** 로그인 폼 내용(순수 표시). <form> 안에서 렌더된다. 상태: 기본·오류·429·로딩. */
export function LoginFormView({ pending, error, email, next, notice }: Props) {
  const invalid = error === "credentials" || undefined;
  const describedBy = error ? ERROR_ID : undefined;
  return (
    <div className="grid gap-4">
      {notice && !error && <AuthAlert tone="success">{notice}</AuthAlert>}
      {error && <AuthAlert tone="danger" id={ERROR_ID}>{AUTH_ERROR_MESSAGES[error]}</AuthAlert>}
      <input type="hidden" name="next" value={next} />
      <AuthField label="이메일" id="email" name="email" type="email" autoComplete="email" required defaultValue={email} aria-invalid={invalid} aria-describedby={describedBy} />
      <AuthField label="비밀번호" id="password" name="password" type="password" autoComplete="current-password" required aria-invalid={invalid} aria-describedby={describedBy} />
      <SubmitButton pending={pending}>{pending ? "로그인 중" : "로그인"}</SubmitButton>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AuthLink href="/forgot-password">비밀번호 찾기</AuthLink>
        <AuthLink href="/terms">이용약관·개인정보</AuthLink>
      </div>
    </div>
  );
}
