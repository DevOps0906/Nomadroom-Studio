import { cn } from "@/lib/utils";

/** 로그아웃: POST /auth/signout (Origin 검사). JS 없이 동작한다. */
export function SignOutButton({ className }: { className?: string }) {
  return (
    <form action="/auth/signout" method="post">
      <button
        type="submit"
        className={cn(
          "inline-flex min-h-11 items-center justify-center rounded-control border border-input bg-surface px-4 text-body font-semibold text-text hover:bg-surface-alt outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        로그아웃
      </button>
    </form>
  );
}
