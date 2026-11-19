"""가짜 FastAPI(W-05~W-09)·Storage(서명 URL)와 lavfi로 만든 합성 미디어(저작물 샘플 없음, F10)."""

import json
import secrets
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from production.adapter import PRESET_VERSION
from production.api import Task, WorkerApi
from production.media import Media

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg·ffprobe 없음")

API_BASE = "https://api.test"
STORAGE = "https://storage.test"


def fake_token() -> str:
    # gitleaks 회피: 실행 때 조립(저장소에 토큰 모양 문자열을 두지 않는다)
    return str(uuid.uuid4()) + "." + secrets.token_urlsafe(24)


class FakeServer:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls: list[tuple[str, str]] = []
        self.inputs: dict[str, tuple[str, bytes]] = {}  # kind → (asset_id, 내용)
        # task-045: 같은 kind 여러 건·parent_asset_id(쇼핑). {asset_id, kind, body, parent?}
        self.input_items: list[dict] = []
        self.drop_on_reissue: set[str] = set()  # 재발급(2번째 W-06부터) 응답에서 뺄 asset_id
        self.claim_bodies: list[bytes] = []
        self.expire_first_inputs = False
        self.reject_first_upload = False
        self.progress_status = 200
        self.finish_status = 200
        self.finish_statuses: list[int] = []  # 앞에서부터 한 번씩 쓰고, 비면 finish_status
        self.storage_base = STORAGE
        self.finished: list[dict] = []
        self.progress: list[dict] = []
        self.issued: dict[str, dict] = {}  # 업로드 asset_id → 항목
        self.uploaded: dict[str, bytes] = {}
        self.sigs: set[str] = set()
        self._inputs_calls = 0
        self._uploads = 0

    # --- 서명 URL ---
    def _sign(self, kind: str, asset_id: str) -> str:
        sig = secrets.token_urlsafe(16)
        self.sigs.add(sig)
        return f"{self.storage_base}/object/{kind}/{asset_id}?token={sig}"

    def api_handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == f"Bearer {self.token}"
        path = request.url.path
        self.calls.append((request.method, path))
        parts = path.removeprefix("/worker/v1/production/").split("/")
        if parts == ["claim"]:
            self.claim_bodies.append(request.content)
            return httpx.Response(204)
        _, _, action = parts
        if action == "inputs":
            self._inputs_calls += 1
            expired = self.expire_first_inputs and self._inputs_calls == 1
            exp = datetime.now(UTC) + (timedelta(seconds=-5) if expired else timedelta(minutes=10))
            return httpx.Response(
                200,
                json={
                    "inputs": [
                        {
                            "asset_id": aid,
                            "kind": k,
                            "download_url": self._sign("in", aid),
                            "expires_at": exp.isoformat(),
                        }
                        for k, (aid, _) in self.inputs.items()
                    ]
                    + [
                        {
                            "asset_id": it["asset_id"],
                            "kind": it["kind"],
                            "download_url": self._sign("in", it["asset_id"]),
                            "expires_at": exp.isoformat(),
                            "parent_asset_id": it.get("parent"),
                        }
                        for it in self.input_items
                        if self._inputs_calls == 1 or it["asset_id"] not in self.drop_on_reissue
                    ]
                },
            )
        if action == "outputs":
            items = []
            for it in json.loads(request.content)["items"]:
                aid = str(uuid.uuid4())
                self.issued[aid] = it
                exp = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
                items.append(
                    {
                        "asset_id": aid,
                        "kind": it["kind"],
                        "upload_url": self._sign("out", aid),
                        "expires_at": exp,
                    }
                )
            return httpx.Response(200, json={"items": items})
        if action == "progress":
            self.progress.append(json.loads(request.content))
            if self.progress_status != 200:
                return httpx.Response(self.progress_status, json={"code": "CONFLICT"})
            return httpx.Response(200, json={"ok": True})
        if action == "finish":
            self.finished.append(json.loads(request.content))
            status = self.finish_statuses.pop(0) if self.finish_statuses else self.finish_status
            if status != 200:
                return httpx.Response(status, json={"code": "ERROR"})
            return httpx.Response(200, json={"task": {"status": "done"}})
        return httpx.Response(404)

    def storage_handler(self, request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers  # 서명 URL에 워커 토큰을 보내지 않는다
        _, _, direction, aid = request.url.path.split("/")
        if request.url.params.get("token") not in self.sigs:
            return httpx.Response(400)
        if direction == "in" and request.method == "GET":
            for asset_id, body in self.inputs.values():
                if asset_id == aid:
                    return httpx.Response(200, content=body)
            for it in self.input_items:
                if it["asset_id"] == aid:
                    return httpx.Response(200, content=it["body"])
            return httpx.Response(404)
        if direction == "out" and request.method == "PUT":
            self._uploads += 1
            if self.reject_first_upload and self._uploads == 1:
                return httpx.Response(403)
            body = request.read()
            assert len(body) == self.issued[aid]["size_bytes"]
            assert request.headers["content-type"] == self.issued[aid]["mime"]
            self.uploaded[aid] = body
            return httpx.Response(200, json={"Key": aid})
        return httpx.Response(405)


@pytest.fixture
def server() -> FakeServer:
    return FakeServer(fake_token())


@pytest.fixture
def api(server: FakeServer):
    client = WorkerApi(
        API_BASE,
        server.token,
        transport=httpx.MockTransport(server.api_handler),
        storage_transport=httpx.MockTransport(server.storage_handler),
    )
    yield client
    client.close()


@pytest.fixture
def media() -> Media:
    return Media(FFMPEG or "ffmpeg", FFPROBE or "ffprobe")


def _ffmpeg(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, Path]:
    """lavfi testsrc+sine 합성 원본(가로 640×360, 4초)·훅 음성(0.6초, 3초)."""
    if not FFMPEG:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("samples")
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=25:duration=4",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=4",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(d / "src.mp4"),
    )
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=660:duration=0.6", str(d / "hook.wav"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=660:duration=3", str(d / "hook_long.wav"))
    (d / "note.txt").write_text("not media", encoding="utf-8")
    return {p.stem: p for p in d.iterdir()}


def make_task(kind: str, **kw) -> Task:
    base = {
        "kind": kind,
        "id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "job_kind": "general",
        "format": "category",
        "preset_version": PRESET_VERSION,
        "lang": "ko",
    }
    return Task.model_validate({**base, **kw})


def make_spec(**over) -> dict:
    spec = {
        "lang": "ko",
        "header": {"lines": ["테스트 제목", "둘째 줄"]},
        "hook": {"text": "이렇게 된다고?", "audio_asset_id": str(uuid.uuid4())},
        "duration": 2.0,
        "shots": [
            {"start": 0, "end": 1, "scale": 1.0, "y": 0},
            {"start": 1, "end": 2, "scale": 1.2, "y": -100},
        ],
        "items": [
            {"start": 0, "end": 1.2, "kind": "white", "text": "이렇게 된다고?"},
            {"start": 1.2, "end": 2, "kind": "emph", "text": "완성", "y": 400},
        ],
    }
    spec.update(over)
    return spec


def ffprobe_streams(path: Path) -> list[dict]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
    )
    return json.loads(out.stdout)["streams"]
