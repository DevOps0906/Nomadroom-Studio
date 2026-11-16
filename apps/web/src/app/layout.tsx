import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "노마드룸 스튜디오",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
