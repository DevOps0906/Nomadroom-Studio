# 제3자 코드·자산 출처 (apps/worker)

## 이식한 코드
- 출처: `카테고리형 영상제작_배포용 .zip`의 `category-shorts/`(scripts/common.py·prepare.py·render.py·tts.py, references/project-format.md).
- 권리: 사용자 결정(2026-11-19, `tasks/task-024.md#착수-결정`) — 저장소에 복사·수정해 쓸 권리 있음.
- 이식 위치와 변경: `production/prepare.py`(URL 다운로드 제거, 작업 폴더 고정 이름, ffmpeg 입력 보안), `production/render.py`(ko 전용, 실패 코드 예외, 중단·진행 콜백), `production/hook_audio.py`(tts.py의 첨부 음성 무음 정리만, TTS 제외), `production/media.py`(common.py의 ffmpeg 호출을 ffprobe·화이트리스트로 대체).

## 폰트 (SIL Open Font License 1.1, 파일 무수정)
| 파일 | 원본 | SHA-256 (배포본 checksums.json과 대조 일치) | 라이선스 |
|---|---|---|---|
| `fonts/Pretendard-Black.otf` | https://github.com/orioncactus/pretendard | `94628b0bcea8936b6e5c30d98d685eb9bbaffb0fe2ed255542ecc656c248e021` | `licenses/Pretendard-OFL.txt` |
| `fonts/NotoSansCJKkr-Bold.otf` | https://github.com/notofonts/noto-cjk | `26d0c6748500a0444844280b308f5b62c7ae92ac6c6ac88148e502dd211eb52a` | `licenses/NotoSansCJK-OFL.txt` |
| `fonts/NotoSansCJKjp-Bold.otf` | https://github.com/notofonts/noto-cjk 태그 `Sans2.004` `Sans/OTF/Japanese/NotoSansCJKjp-Bold.otf` | `e53dcb0dcb2922e45d01aae1ebd2f382bb81d4229b18b6b883bd170678af1f76` | `licenses/NotoSansCJK-OFL.txt` |
| `fonts/NotoSansCJKjp-Black.otf` | https://github.com/notofonts/noto-cjk 태그 `Sans2.004` `Sans/OTF/Japanese/NotoSansCJKjp-Black.otf` | `cd66686594a861a42fe752990a406fcedafb51b3a91d6639f30f8948f7a10b4d` | `licenses/NotoSansCJK-OFL.txt` |
- 일본어 글꼴(task-050 K5): 공식 저장소 태그 `Sans2.004`에서 받은 파일 그대로(2026-11-20). 같은 태그의 `Sans/OTF/Korean/NotoSansCJKkr-Bold.otf` SHA-256이 위 KR 파일과 일치하고, 태그 루트 `LICENSE`가 `licenses/NotoSansCJK-OFL.txt`와 같은 내용이라 라이선스 파일을 재사용한다. lang=ja 렌더는 제목 Black·자막·오버레이·CTA·표기 Bold(`production/fonts.py`), 한국어 글꼴로 대체하지 않는다.
- 예능형(task-036) 글꼴 대체: 예제 글꼴 Cafe24 Ohsquare·여기어때 잘난체는 실습 zip에 파일·라이선스가 없어 상업 이용·동봉 근거가 없다(`docs/01_PRD.md#7` Q9) → 동봉하지 않고 위 Pretendard-Black으로 대체, 글리프가 없으면 NotoSansCJKkr-Bold(D-V3·W8·W9). 리포트 `font_substituted: true`. 새 글꼴 파일 추가·다운로드 없음.

## 외부 실행 파일
- ffmpeg·ffprobe: 운영자 PC에 설치된 시스템 실행 파일을 subprocess로 호출만 한다(저장소·배포물에 포함하지 않음). GPL 빌드일 수 있으나 링크·재배포가 없어 내부 도구로 수용(F11). imageio-ffmpeg 동봉 바이너리는 쓰지 않는다.

## Python 의존성 (uv.lock 고정)
- httpx (BSD-3-Clause) · Pillow (MIT-CMU) · pydantic-settings (MIT). 개발: pytest (MIT) · ruff (MIT).
