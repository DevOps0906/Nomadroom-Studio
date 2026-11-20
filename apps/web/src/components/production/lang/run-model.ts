// PROD-03 ja 탭 판단(순수). 서버가 정본이고 여기는 버튼 노출·안내 문구만 정한다.

export type JaRunState = { canRequest: boolean; message: string };

export function jaRunState(ja: { approved_at: string | null } | null): JaRunState {
  if (!ja) return { canRequest: false, message: "일본어판이 아직 없습니다. 편집안의 ja 탭에서 \"일본어판 만들기\"로 시작하세요." };
  if (!ja.approved_at) return { canRequest: false, message: "일본어판이 아직 승인되지 않았습니다. 편집안의 ja 탭에서 수정·승인하세요." };
  return { canRequest: true, message: "승인됨 — 렌더 요청을 눌러 시작(ko와 별도 렌더입니다)" };
}

export const TTS_DISCLOSURE = "대사·문구가 외부 음성 합성(TTS) 서비스로 전송됩니다.";
