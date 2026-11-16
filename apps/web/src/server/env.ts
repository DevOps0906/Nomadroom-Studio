import "server-only";

// 서버 전용 환경변수. NEXT_PUBLIC_ 접두사를 쓰지 않아 브라우저 번들에 들어가지 않는다.
function required(name: "SUPABASE_URL" | "SUPABASE_PUBLISHABLE_KEY" | "APP_ORIGIN"): string {
  const value = process.env[name];
  if (!value) throw new Error(`환경변수 ${name}이(가) 없습니다`);
  return value;
}

export function getSupabaseEnv() {
  return { url: required("SUPABASE_URL"), publishableKey: required("SUPABASE_PUBLISHABLE_KEY") };
}

/** 정규화된 앱 Origin (예: https://studio.example.com) */
export function getAppOrigin(): string {
  return new URL(required("APP_ORIGIN")).origin;
}
