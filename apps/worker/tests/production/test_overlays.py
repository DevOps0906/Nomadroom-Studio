"""task-032 댓글·출처 오버레이: 정규화·카드·어댑터 연결·실제 렌더(608×1080·30fps)."""

import pytest
from worker_fakes import ffprobe_streams, make_spec, needs_ffmpeg

from production.adapter import to_project
from production.errors import RenderFailed, TextTooLong
from production.media import Cancel
from production.overlays import W, draw_card, normalize, text_units
from production.render import render


def ov(**kw) -> dict:
    return {
        "kind": "comment",
        "text": "댓글 문구",
        "start": 0.2,
        "end": 1.0,
        "x": 304,
        "y": 200,
        **kw,
    }


def test_adapter_passes_overlays_and_empty_default():
    assert to_project(make_spec(), "ko")["overlays"] == []
    project = to_project(make_spec(overlays=[ov(), ov(kind="source", y=900)]), "ko")
    assert [o["kind"] for o in project["overlays"]] == ["comment", "source"]


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "comment"},
        ov(kind="image"),
        ov(text=" "),
        ov(text="a\nb"),
        ov(text="가" * 41),
        ov(text="W" * 41),
        ov(end=2.5),
        ov(start=-1),
        ov(x=-1),
        ov(y=1081),
        ov(x=True),
        ov(ref="https://x.test/a.png", text=3),
    ],
)
def test_adapter_rejects_bad_overlay(bad):
    with pytest.raises(RenderFailed):
        to_project(make_spec(overlays=[bad]), "ko")


def test_same_kind_overlap_rejected_other_kind_ok():
    with pytest.raises(RenderFailed):
        normalize([ov(), ov(start=0.5, end=1.5)], 2.0)
    assert len(normalize([ov(), ov(kind="source", start=0.5, end=1.5)], 2.0)) == 2


def test_card_draws_inside_frame_and_clamps_edges():
    layer = draw_card(normalize([ov(x=0, y=0)], 2.0)[0])
    bbox = layer.getchannel("A").getbbox()
    assert bbox is not None and bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] <= W


def test_overlay_count_limit():
    spans = [ov(start=i * 0.1, end=i * 0.1 + 0.05) for i in range(21)]
    assert len(normalize(spans[:20], 5.0)) == 20
    with pytest.raises(RenderFailed):
        normalize(spans, 5.0)


@pytest.mark.parametrize("kind", ["comment", "source"])
@pytest.mark.parametrize(
    "text",
    [
        "W" * 40,
        "M" * 40,
        "뷁" * 40,
        "鬱" * 40,
        "가" * 40,
        "@%" * 20,
        "Wm" * 20,
        "-" * 80,
        "(" * 80,
        "W" * 20 + "뷁" * 20,
    ],
)
def test_max_units_text_fits_card_width_at_min_font(kind, text):
    assert text_units(text) <= 80
    o = normalize([ov(kind=kind, text=text, x=304)], 2.0)[0]
    bbox = draw_card(o).getchannel("A").getbbox()  # TextTooLong이면 여기서 실패
    assert bbox is not None and bbox[2] - bbox[0] <= 540 and bbox[0] >= 0 and bbox[2] <= W


def test_card_too_long_text_raises():
    with pytest.raises(TextTooLong):
        draw_card({"kind": "comment", "text": "W" * 60, "start": 0, "end": 1, "x": 300, "y": 300})


def test_overlay_text_is_not_a_filter_string():
    # 필터 메타 문자가 들어 있어도 그림 글자로만 쓰인다(렌더 실패 없음)
    card = draw_card(normalize([ov(text="';[a]movie=/etc/passwd,%{n}")], 2.0)[0])
    assert card.getchannel("A").getbbox() is not None


@needs_ffmpeg
def test_render_with_overlays_keeps_output_spec(media, samples, tmp_path):
    spec = make_spec(
        overlays=[ov(), ov(kind="source", text="출처: 직접 촬영", start=0.5, end=1.8, y=950)]
    )
    project = to_project(spec, "ko")
    cancel = Cancel()
    source_meta = media.probe(samples["src"], cancel)
    out = tmp_path / "out.mp4"
    result = render(
        project, samples["src"], source_meta, samples["hook"], 0.6, out, media, cancel,
        lambda stage, pct: None,
    )  # fmt: skip
    assert (result["width"], result["height"], result["fps"]) == (608, 1080, 30)
    v = next(s for s in ffprobe_streams(out) if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["r_frame_rate"]) == (608, 1080, "30/1")
