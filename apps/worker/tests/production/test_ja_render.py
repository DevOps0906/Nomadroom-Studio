"""task-050 일본어판 렌더(category·shopping, 가짜 API·Storage, 실제 ffmpeg).

K5 JP 글꼴(제목·자막·오버레이·CTA 모두, 카테고리 제목 둘째 줄 흰색), K6 글자 단위 줄바꿈·금칙,
K7 결과 파일명·report 글꼴·lang, K4 훅 TTS 꺼짐이면 tts_failed(대체 없음), ko 회귀.
"""

import json
import subprocess
import uuid

import pytest
from PIL import Image, ImageFont
from test_shopping_render import _setup, _task, ssamples  # noqa: F401  (fixture 등록)
from worker_fakes import FFMPEG, ffprobe_streams, make_spec, make_task, needs_ffmpeg

from production import fonts as fonts_mod
from production import tts as tts_mod
from production.config import TtsSettings
from production.runner import run_task
from production.shopping.text import NO_END, NO_START, wrap_ja
from production.variety.text import FALLBACK_FONT, PRIMARY_FONT, pick_font

JP = {fonts_mod.NOTO_JP_BOLD, fonts_mod.NOTO_JP_BLACK}
JA_SCRIPT = [
    "足が痛い日が多かったです。",
    "このインソールで歩いてみました。",
    "長く歩いても疲れにくいです。",
    "プロフィールのリンクから確認してね。",
]


def _uploaded(server, kind):
    return [b for aid, b in server.uploaded.items() if server.issued[aid]["kind"] == kind]


@pytest.fixture
def used_fonts(monkeypatch) -> set:
    """렌더 중 ImageFont.truetype이 연 글꼴 파일 경로(JP 글꼴 사용 단언용)."""
    seen: set = set()
    real = ImageFont.truetype

    def spy(font=None, *args, **kw):
        seen.add(str(font))
        return real(font, *args, **kw)

    monkeypatch.setattr(ImageFont, "truetype", spy)
    return seen


def _ja_category_spec(**over) -> dict:
    spec = make_spec(
        lang="ja",
        header={"lines": ["テストタイトル", "二行目"]},
        hook={"text": "こうなるの？", "audio_asset_id": str(uuid.uuid4())},
        items=[
            {"start": 0, "end": 1.2, "kind": "white", "text": "こうなるの？"},
            {"start": 1.2, "end": 2, "kind": "emph", "text": "完成", "y": 400},
        ],
        overlays=[
            {"kind": "comment", "text": "すごい！", "start": 0.2, "end": 1.0, "x": 300, "y": 600}
        ],
    )
    spec.update(over)
    return spec


def _category_inputs(server, samples) -> None:
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.inputs["hook_audio"] = (str(uuid.uuid4()), samples["hook"].read_bytes())


def _yellow_in_title_line2(mp4) -> int:
    """제목 둘째 줄(중심 y 228) 띠에서 노란색(#FFDC00 근처) 픽셀 수."""
    out = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", "0.5", "-i", str(mp4)]
        + ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        check=True,
        capture_output=True,
    )
    img = Image.frombytes("RGB", (608, 1080), out.stdout).crop((0, 195, 608, 262))
    return sum(1 for r, g, b in img.get_flattened_data() if r > 200 and g > 170 and b < 90)


# --- 카테고리형 ---------------------------------------------------------------------


@needs_ffmpeg
def test_category_ja_render_uses_jp_fonts_and_white_title(
    api, server, media, samples, tmp_path, used_fonts
):
    _category_inputs(server, samples)
    task = make_task("render", lang="ja", spec=_ja_category_spec())
    assert run_task(api, task, tmp_path, media, 60) == "done", server.finished
    report = json.loads(_uploaded(server, "report")[0])
    assert report["output"] == "result_ja.mp4" and report["lang"] == "ja"
    assert report["fonts"] == ["NotoSansCJKjp-Black", "NotoSansCJKjp-Bold"]
    assert used_fonts and used_fonts <= {str(p) for p in JP}  # 제목·자막·오버레이 모두 JP
    mp4 = tmp_path / "ja.mp4"
    mp4.write_bytes(_uploaded(server, "output_mp4")[0])
    video = next(s for s in ffprobe_streams(mp4) if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (608, 1080)
    assert _yellow_in_title_line2(mp4) == 0  # 일본어 제목 둘째 줄은 흰색


@needs_ffmpeg
def test_category_ko_regression_fonts_name_and_yellow(
    api, server, media, samples, tmp_path, used_fonts
):
    _category_inputs(server, samples)
    assert run_task(api, make_task("render", spec=make_spec()), tmp_path, media, 60) == "done"
    report = json.loads(_uploaded(server, "report")[0])
    assert report["output"] == "result_ko.mp4" and report["lang"] == "ko"
    assert report["fonts"] == ["Pretendard-Black", "NotoSansCJKkr-Bold"]
    assert not used_fonts & {str(p) for p in JP}
    mp4 = tmp_path / "ko.mp4"
    mp4.write_bytes(_uploaded(server, "output_mp4")[0])
    assert _yellow_in_title_line2(mp4) > 50  # 한국어 둘째 줄 노랑 유지


@needs_ffmpeg
def test_category_ja_tts_disabled_is_tts_failed_without_fallback(
    api, server, media, samples, tmp_path
):
    _category_inputs(server, samples)  # 녹음이 있어도 대체하지 않는다
    spec = _ja_category_spec(hook={"text": "こうなるの？", "tts": {"voice": "ja-JP-NanamiNeural"}})
    task = make_task("render", lang="ja", spec=spec)
    assert run_task(api, task, tmp_path, media, 60, tts_cfg=TtsSettings()) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "audio",
        "error_code": "tts_failed",
    }
    assert not server.uploaded


@needs_ffmpeg
def test_category_ja_tts_uses_ja_voice(api, server, media, samples, tmp_path, monkeypatch):
    calls: list = []

    async def synth(text, voice, rate, out, cfg):
        calls.append((text, voice))
        out.write_bytes(samples["hook"].read_bytes())

    monkeypatch.setattr(tts_mod, "edge_save", synth)
    server.inputs["source"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    spec = _ja_category_spec(hook={"text": "こうなるの？", "tts": {"voice": "ja-JP-NanamiNeural"}})
    task = make_task("render", lang="ja", spec=spec)
    on = TtsSettings(enabled=True, timeout_sec=30)
    assert run_task(api, task, tmp_path, media, 60, tts_cfg=on) == "done", server.finished
    assert calls == [("こうなるの？", "ja-JP-NanamiNeural")]


# --- 쇼핑 ---------------------------------------------------------------------------


def _ja_shopping_spec(server, ss) -> dict:
    spec, _ = _setup(server, ss)
    spec["lang"] = "ja"
    spec["script"] = [{"text": t} for t in JA_SCRIPT]
    spec["cta"] = {"text": "プロフィールのリンクをチェック"}
    spec["disclosure"] = {"text": "PR"}
    return spec


@needs_ffmpeg
def test_shopping_ja_render_uses_jp_font_and_pr(
    api,
    server,
    media,
    ssamples,  # noqa: F811
    tmp_path,
    used_fonts,
):
    spec = _ja_shopping_spec(server, ssamples)
    assert run_task(api, _task(spec, lang="ja"), tmp_path, media, 60) == "done", server.finished
    report = json.loads(_uploaded(server, "report")[0])
    assert report["output"] == "result_ja.mp4" and report["lang"] == "ja"
    assert report["disclosure"] == "PR"
    assert report["fonts"] == ["NotoSansCJKjp-Bold"]
    assert used_fonts == {str(fonts_mod.NOTO_JP_BOLD)}  # 자막·CTA·표기 모두 JP
    mp4 = tmp_path / "ja.mp4"
    mp4.write_bytes(_uploaded(server, "output_mp4")[0])
    video = next(s for s in ffprobe_streams(mp4) if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)


@needs_ffmpeg
def test_shopping_ko_regression_output_name_and_fonts(
    api,
    server,
    media,
    ssamples,  # noqa: F811
    tmp_path,
    used_fonts,
):
    spec, _ = _setup(server, ssamples)
    assert run_task(api, _task(spec), tmp_path, media, 60) == "done"
    report = json.loads(_uploaded(server, "report")[0])
    assert report["output"] == "result_ko.mp4" and report["lang"] == "ko"
    assert not used_fonts & {str(p) for p in JP}


def test_shopping_ja_lang_mismatch_rejected(api, server, media, ssamples, tmp_path):  # noqa: F811
    spec = _ja_shopping_spec(server, ssamples)
    assert run_task(api, _task(spec, lang="ko"), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"


# --- 글꼴 선택·줄바꿈 -----------------------------------------------------------------


def test_pick_font_ja_uses_only_jp_and_ko_unchanged():
    assert pick_font("足が痛い", "ja") == fonts_mod.NOTO_JP_BOLD
    assert pick_font("PR", "ja") == fonts_mod.NOTO_JP_BOLD  # 라틴만이어도 JP 글꼴
    assert pick_font("발이 아파요") == PRIMARY_FONT and pick_font("관상 觀相") == FALLBACK_FONT


def test_jp_fonts_present_and_named():
    for path, style in ((fonts_mod.NOTO_JP_BOLD, "Bold"), (fonts_mod.NOTO_JP_BLACK, "Black")):
        assert ImageFont.truetype(str(path), 20).getname() == ("Noto Sans CJK JP", style)


TEXTS = [
    "このインソールを入れて、長い時間歩いてみました。「本当に」疲れにくい！",
    "ちょっと待って……これ、すごくない？（個人の感想です）ぜひチェックしてね。",
    "キャッシュレスでショッピング、ポイントもたまる「お得」なサービスです。",
]


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("max_w", [120, 150, 190, 230, 300])
def test_wrap_ja_char_level_with_kinsoku(text, max_w):
    font = ImageFont.truetype(str(fonts_mod.NOTO_JP_BOLD), 24)
    lines = wrap_ja(text, font, max_w)
    assert "".join(lines) == text  # 글자를 잃거나 바꾸지 않는다
    assert len(lines) > 1
    for line in lines[1:]:
        assert line[0] not in NO_START, lines  # 행두 금칙
    for line in lines[:-1]:
        assert line[-1] not in NO_END, lines  # 행말 금칙


def test_wrap_ja_pushes_previous_char_before_closing_punct():
    font = ImageFont.truetype(str(fonts_mod.NOTO_JP_BOLD), 20)
    w = font.getlength("あいうえ")
    assert wrap_ja("あいうえ。かき", font, w) == ["あいう", "え。かき"]
    assert wrap_ja("あいう「えお」", font, w) == ["あいう", "「えお」"]
