"use client";

import { useEffect } from "react";

// 언어 탭 전환 전 미저장 확인. 편집 폼(3종)·JaPanel이 dirty를 등록하고 탭 링크가 확인한다.
// 탭은 서버 컴포넌트 페이지에 있고 dirty는 폼에 있어, 화면에 하나뿐인 값을 모듈 변수로 공유한다.

export const LANG_LEAVE_CONFIRM = "저장하지 않은 변경이 있습니다. 언어 탭을 바꾸면 화면의 변경은 사라집니다. 이동할까요?";

let dirty = false;

export const setLangDirty = (v: boolean) => {
  dirty = v;
};

/** 이동해도 되면 true. 미저장 변경이 있으면 확인창(취소하면 false). */
export function confirmLangLeave(confirmFn: (m: string) => boolean = (m) => window.confirm(m)): boolean {
  return !dirty || confirmFn(LANG_LEAVE_CONFIRM);
}

export function useLangDirty(value: boolean) {
  useEffect(() => {
    setLangDirty(value);
    return () => setLangDirty(false);
  }, [value]);
}
