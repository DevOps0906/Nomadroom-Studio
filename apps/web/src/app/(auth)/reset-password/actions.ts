"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getRecoverySession } from "@/server/auth/recovery-session";
import { clearSupabaseCookies } from "@/server/auth/session";
import { RECOVERY_COOKIE } from "@/server/auth/recovery";

export type ResetState = { error: string | null };

export async function resetPassword(_prev: ResetState, formData: FormData): Promise<ResetState> {
  const password = String(formData.get("password") ?? "");
  const confirm = String(formData.get("confirm") ?? "");
  const supabase = await getRecoverySession();
  if (!supabase) return { error: "재설정 링크가 만료되었습니다. 비밀번호 찾기를 다시 진행하세요." };
  if (!password) return { error: "새 비밀번호를 입력하세요." };
  if (password !== confirm) return { error: "두 비밀번호가 일치하지 않습니다." };

  const { error } = await supabase.auth.updateUser({ password });
  if (error) {
    if (error.status === 429) return { error: "시도가 너무 많습니다. 5분 뒤 다시 시도하세요." };
    if (error.code === "same_password") return { error: "이전과 다른 비밀번호를 입력하세요." };
    if (error.code === "weak_password") return { error: "비밀번호가 너무 약합니다. 더 길고 복잡하게 입력하세요." };
    return { error: "비밀번호를 변경하지 못했습니다. 잠시 뒤 다시 시도하세요." };
  }
  // 비밀번호가 바뀌었으니 다른 기기의 세션도 모두 끊는다.
  const { error: signOutError } = await supabase.auth.signOut({ scope: "global" });
  const store = await cookies();
  if (signOutError) clearSupabaseCookies(store);
  store.delete(RECOVERY_COOKIE);
  redirect("/login?reset=done");
}
