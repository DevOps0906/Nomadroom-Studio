import { redirect } from "next/navigation";

// MON-D1은 /monitor 안 다이얼로그다(spec). 독립 페이지 주소는 /monitor로 보낸다. 근거: tasks/task-013.md.
export default function ProfilesPage(): never {
  redirect("/monitor");
}
