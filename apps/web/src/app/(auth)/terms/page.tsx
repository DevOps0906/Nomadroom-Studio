import type { Metadata } from "next";
import { AuthCard, AuthLink } from "@/components/auth/auth-ui";

export const metadata: Metadata = { title: "이용약관·개인정보 · Nomadroom Studio" };

// 공개 페이지(로그인 불필요). 내부 운영자 전용 도구 안내.
export default function TermsPage() {
  return (
    <AuthCard title="이용약관·개인정보">
      <div className="grid gap-4 text-body text-text">
        <section className="grid gap-1">
          <h2 className="font-semibold">이용 대상</h2>
          <p className="text-text-muted">Nomadroom Studio는 등록된 내부 운영자만 쓰는 업무 도구입니다. 계정은 관리자가 발급합니다.</p>
        </section>
        <section className="grid gap-1">
          <h2 className="font-semibold">수집하는 개인정보</h2>
          <p className="text-text-muted">로그인에 쓰는 이메일 주소만 수집합니다. 로그인과 비밀번호 재설정 안내 외의 용도로 쓰지 않습니다.</p>
        </section>
        <section className="grid gap-1">
          <h2 className="font-semibold">문의</h2>
          <p className="text-text-muted">계정·개인정보 관련 문의는 워크스페이스 관리자에게 하세요.</p>
        </section>
        <AuthLink href="/login">로그인으로 돌아가기</AuthLink>
      </div>
    </AuthCard>
  );
}
