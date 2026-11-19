"""prepare·render 전체 흐름(가짜 API·Storage, 실제 ffmpeg).
F10: 산출물 ffprobe 608×1080·30/1·h264·aac."""

import json
import logging
import uuid

from worker_fakes import ffprobe_streams, make_spec, make_task, needs_ffmpeg

from production.adapter import PRESET_VERSION
from production.runner import run_task

pytestmark = needs_ffmpeg


def _render_task(**kw):
    return make_task("render", spec=kw.pop("spec", make_spec()), **kw)


def _set_render_inputs(server, samples, hook="hook"):
    server.inputs["source"] = (str(uuid.uuid4()), _prepared_source(samples))
    if hook:
        server.inputs["hook_audio"] = (str(uuid.uuid4()), samples[hook].read_bytes())


_SOURCE_CACHE: dict[str, bytes] = {}


def _prepared_source(samples) -> bytes:
    # render 입력 source는 prepare 산출물과 같은 mp4(합성 원본 그대로 사용)
    return _SOURCE_CACHE.setdefault("src", samples["src"].read_bytes())


def _uploaded(server, kind):
    return [
        (aid, body) for aid, body in server.uploaded.items() if server.issued[aid]["kind"] == kind
    ]


# --- prepare ----------------------------------------------------------------------


def test_prepare_done(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    task = make_task("prepare", source_start_sec=0.5, segment_len_sec=3.0)
    assert run_task(api, task, tmp_path, media, 60) == "done"
    body = server.finished[-1]
    assert body["status"] == "done"
    assert set(body["meta"]) == {"duration_sec", "width", "height", "has_audio"}
    assert body["meta"]["has_audio"] is True
    assert abs(body["meta"]["duration_sec"] - 3.0) < 0.15
    kinds = [server.issued[a]["kind"] for a in body["asset_ids"]]
    assert kinds.count("source") == 1 and kinds.count("analysis") == 1 and "sheet" in kinds
    analysis = json.loads(_uploaded(server, "analysis")[0][1])
    assert analysis["source_start"] == 0.5
    assert {p["stage"] for p in server.progress} >= {"download", "extract", "sheet", "upload"}
    assert not (tmp_path / str(task.id)).exists()  # F5: 성공 뒤 폴더 삭제


def test_prepare_expired_input_url_is_reissued(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.expire_first_inputs = True
    task = make_task("prepare", segment_len_sec=2.0)
    assert run_task(api, task, tmp_path, media, 60) == "done"
    inputs_calls = [c for c in server.calls if c[1].endswith("/inputs")]
    assert len(inputs_calls) == 2  # F6: W-06 재호출


def test_prepare_upload_rejected_gets_new_asset_id(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.reject_first_upload = True
    task = make_task("prepare", segment_len_sec=2.0)
    assert run_task(api, task, tmp_path, media, 60) == "done"
    outputs_calls = [c for c in server.calls if c[1].endswith("/outputs")]
    assert len(outputs_calls) == 2  # F6: W-07 재호출 → 새 asset_id
    ids = server.finished[-1]["asset_ids"]
    assert all(a in server.uploaded for a in ids)  # 마지막(성공한) id만
    assert len(ids) == len(set(ids))


def test_prepare_range_invalid(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    task = make_task("prepare", source_start_sec=10.0, segment_len_sec=2.0)
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "prepare",
        "error_code": "range_invalid",
    }


def test_prepare_non_media_input_invalid(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["note"].read_bytes())
    assert run_task(api, make_task("prepare"), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "input_invalid"


# --- render -----------------------------------------------------------------------


def test_render_done_ffprobe(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples)
    task = _render_task()
    assert run_task(api, task, tmp_path, media, 60) == "done"
    body = server.finished[-1]
    assert body["status"] == "done" and "meta" not in body
    kinds = sorted(server.issued[a]["kind"] for a in body["asset_ids"])
    assert kinds == ["hook_audio", "output_mp4", "report"]
    mp4 = tmp_path / "out.mp4"
    mp4.write_bytes(_uploaded(server, "output_mp4")[0][1])
    streams = ffprobe_streams(mp4)  # F10
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (608, 1080)
    assert video["r_frame_rate"] == "30/1"
    assert video["codec_name"] == "h264" and audio["codec_name"] == "aac"
    report = json.loads(_uploaded(server, "report")[0][1])
    assert report["preset_version"] == PRESET_VERSION
    assert report["hook_audio_asset_id"] == server.inputs["hook_audio"][0]  # F8
    assert {p["stage"] for p in server.progress} >= {"download", "audio", "compose", "upload"}


def test_render_hook_too_long(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples, hook="hook_long")
    assert run_task(api, _render_task(), tmp_path, media, 60) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "audio",
        "error_code": "hook_too_long",
    }


def test_render_text_too_long(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples)
    spec = make_spec(header={"lines": ["너무 긴 제목" * 30, "둘째"]})
    assert run_task(api, _render_task(spec=spec), tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "text_too_long"
    assert server.finished[-1]["error_stage"] == "render"


def test_render_without_hook_audio_is_audio_missing(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples, hook=None)
    assert run_task(api, _render_task(), tmp_path, media, 60) == "failed"
    assert server.finished[-1] == {
        "status": "failed",
        "error_stage": "audio",
        "error_code": "audio_missing",
    }


def test_render_preset_mismatch_is_render_failed(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples)
    task = _render_task(preset_version="category-1080-v0")
    assert run_task(api, task, tmp_path, media, 60) == "failed"
    assert server.finished[-1]["error_code"] == "render_failed"
    assert not [c for c in server.calls if c[1].endswith("/inputs")]  # 렌더하지 않음(F9)


def test_progress_409_stops_without_finish(api, server, media, samples, tmp_path):
    _set_render_inputs(server, samples)
    server.progress_status = 409
    task = _render_task()
    assert run_task(api, task, tmp_path, media, 60) == "cancelled"
    assert server.finished == []
    assert not (tmp_path / str(task.id)).exists()


def test_finish_409_is_already_processed(api, server, media, samples, tmp_path):
    server.inputs["source_upload"] = (str(uuid.uuid4()), samples["src"].read_bytes())
    server.finish_status = 409
    task = make_task("prepare", segment_len_sec=1.0)
    assert run_task(api, task, tmp_path, media, 60) == "done"
    assert len(server.finished) == 1  # 재시도하지 않음
    assert not (tmp_path / str(task.id)).exists()


def test_logs_have_no_token_or_signed_url(api, server, media, samples, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    _set_render_inputs(server, samples)
    server.expire_first_inputs = True
    server.reject_first_upload = True
    assert run_task(api, _render_task(), tmp_path, media, 60) == "done"
    text = caplog.text
    secret = server.token.split(".", 1)[1]
    assert server.token not in text and secret not in text
    assert not [s for s in server.sigs if s in text]
    assert "storage.test" not in text and "token=" not in text
    assert str(tmp_path) not in text  # 로컬 경로도 로그 금지
