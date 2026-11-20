"""task-049 일본어판 파생·번역(A-20)·ja 편집(A-12)·승인(A-13) 테스트. Claude는 목 전용.

가짜 DB·Storage·SDK 가로채기·네트워크 차단은 test_ai_draft를 잇고, 번역·ja 저장·승인 RPC는
supabase/migrations/20261120000027_ja_revisions.sql을 본뜬다(실제 SQL은
supabase/tests/production_ja_revisions_test.sql이 검사).
"""

import copy
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.production import translate
from tests.production import test_ai_draft as base
from tests.production.test_ai_draft import AiDB
from tests.production.test_ai_draft_variety import META
from tests.production.test_ai_draft_variety import user_spec as variety_spec
from tests.production.test_jobs_api import (
    REST,
    URL,
    _now,
    _rpc_error,
    cur_updated_at,
    good_spec,
    same_ts,
)
from tests.production.test_shopping_api import review_shop

auth, claude, key, no_network = base.auth, base.claude, base.key, base.no_network

TEXT_KEYS = {"category": "hook", "variety": "subtitles", "shopping": "script"}


@dataclass
class TDB(AiDB):
    """000027 번역·ja 저장·승인 RPC 모의."""

    def _rev(self, rid: Any) -> dict | None:
        return next((r for r in self.revisions if r["id"] == rid), None)

    def _treq(self, j: dict, key: str) -> dict | None:
        return next((e for e in j.setdefault("translate_requests", []) if e["key"] == key), None)

    def _writable(self, j: dict) -> bool:
        ko = self._rev(j["current_revision_id"])
        rendering = any(
            r["job_id"] == j["id"] and r["lang"] == "ja" and r["status"] in ("queued", "running")
            for r in self.runs
        )
        return ko is not None and ko["approved_at"] is not None and not rendering

    def _tjson(self, j: dict, req: dict, replay: bool) -> httpx.Response:
        rev = self._rev(req.get("revision_id"))
        keys = (
            "id",
            "rev_no",
            "spec",
            "origin",
            "validation",
            "approved_at",
            "derived_from",
            "updated_at",
        )
        return httpx.Response(
            200,
            json={
                "replay": replay,
                "request_status": req["status"],
                "translate_count": j.get("translate_count", 0),
                "revision": {k: rev[k] for k in keys} if rev else None,
            },
        )

    def t_reserve(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("t_reserve")
        j = self._locked_job(body)
        if j is None:
            return _rpc_error("NR009")
        j.setdefault("translate_count", 0)
        req = self._treq(j, body["p_key"])
        if req is not None:
            if req["status"] == "pending":
                return _rpc_error("NR018")
            return self._tjson(j, req, True)
        if any(o is not j and self._treq(o, body["p_key"]) for o in self.jobs):
            return _rpc_error("NR011")
        ko = self._rev(body["p_revision"])
        if (
            body["p_revision"] != j["current_revision_id"]
            or ko is None
            or ko["lang"] != "ko"
            or ko["approved_at"] is None
        ):
            return _rpc_error("NR012")
        if not self._writable(j):
            return _rpc_error("NR010")
        if j["translate_count"] >= body["p_limit"]:
            return _rpc_error("NR016")
        recent = datetime.now(UTC) - timedelta(seconds=60)
        if any(datetime.fromisoformat(e["created_at"]) > recent for e in j["translate_requests"]):
            return _rpc_error("NR017")
        req = {
            "key": body["p_key"],
            "kind": "translate",
            "status": "pending",
            "ko_revision_id": body["p_revision"],
            "revision_id": None,
            "created_at": _now(),
        }
        j["translate_requests"].append(req)
        j["translate_count"] += 1
        return self._tjson(j, req, False)

    def _ja_no(self, j: dict) -> int:
        nos = [r["rev_no"] for r in self.revisions if r["job_id"] == j["id"] and r["lang"] == "ja"]
        return max(nos, default=0) + 1

    def _new_ja(self, j: dict, body: dict, derived: str, origin: str) -> dict:
        rev = {
            "id": str(uuid.uuid4()),
            "workspace_id": j["workspace_id"],
            "job_id": j["id"],
            "lang": "ja",
            "rev_no": self._ja_no(j),
            "schema_version": 1,
            "spec": body["p_spec"],
            "origin": origin,
            "validation": body["p_validation"],
            "approved_at": None,
            "approved_by": None,
            "created_by": body["p_user"],
            "created_at": _now(),
            "updated_at": _now(),
            "derived_from": derived,
        }
        self.revisions.append(rev)
        j["current_ja_revision_id"] = rev["id"]
        return rev

    def t_create(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("t_create")
        j = self._locked_job(body)
        req = self._treq(j, body["p_key"]) if j else None
        if req is None or req["status"] != "pending":
            return _rpc_error("NR010")
        if j["current_revision_id"] != req["ko_revision_id"] or not self._writable(j):
            return _rpc_error("NR010")
        rev = self._new_ja(j, body, j["current_revision_id"], "ai_draft")
        req.update(status="done", revision_id=rev["id"])
        return self._tjson(j, req, False)

    def t_fail(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("t_fail")
        j = self._locked_job(body)
        req = self._treq(j, body["p_key"]) if j else None
        if req is not None and req["status"] == "pending":
            req["status"] = "failed"
        return httpx.Response(204)

    def ja_save(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("ja_save")
        j = self._locked_job(body)
        rev = self._rev(j.get("current_ja_revision_id")) if j else None
        if rev is None or not self._writable(j):
            return _rpc_error("NR010")
        if rev["rev_no"] != body["p_base_rev_no"] or not same_ts(
            rev["updated_at"], body["p_base_updated_at"]
        ):
            return _rpc_error("NR011")
        if rev["approved_at"] is None:
            rev.update(spec=body["p_spec"], validation=body["p_validation"], updated_at=_now())
        else:
            rev = self._new_ja(j, body, rev["derived_from"], "user")
        keys = (
            "id",
            "rev_no",
            "spec",
            "origin",
            "validation",
            "approved_at",
            "derived_from",
            "updated_at",
        )
        return httpx.Response(200, json={k: rev[k] for k in keys})

    def ja_approve(self, body: dict) -> httpx.Response:
        self.rpc_calls.append("ja_approve")
        j = self._locked_job(body)
        rev = self._rev(j.get("current_ja_revision_id")) if j else None
        if rev is None or not self._writable(j):
            return _rpc_error("NR010")
        if rev["rev_no"] != body["p_rev_no"] or rev["updated_at"] != body["p_updated_at"]:
            return _rpc_error("NR011")
        if rev["approved_at"] is not None or rev["derived_from"] != j["current_revision_id"]:
            return _rpc_error("NR010")
        rev.update(approved_at=_now(), approved_by=body["p_user"], validation=body["p_validation"])
        return httpx.Response(
            200, json={k: rev[k] for k in ("id", "rev_no", "approved_at", "approved_by")}
        )


@pytest.fixture
def db() -> TDB:
    return TDB()


def _routes(router: respx.MockRouter, db: TDB) -> None:
    for name, fn in (
        ("reserve_translation", db.t_reserve),
        ("create_ja_translation", db.t_create),
        ("fail_translation", db.t_fail),
        ("save_ja_revision", db.ja_save),
        ("approve_ja_revision", db.ja_approve),
    ):
        router.post(f"{REST}/rpc/{name}").mock(side_effect=lambda r, f=fn: f(json.loads(r.content)))


@pytest.fixture
def api(mock_supabase, jwks_payload, db, claude, key) -> Iterator[TestClient]:
    _routes(mock_supabase, db)
    with base._client(mock_supabase, jwks_payload, db, anthropic_api_key=key) as c:
        yield c
    assert all(call.request.url.host == "supabase.test" for call in mock_supabase.calls)


# --- 준비 ------------------------------------------------------------------------


def category_job(db: TDB) -> tuple[dict, dict]:
    job = db.add_job(status="review")
    spec = good_spec()  # hook.audio_asset_id = 녹음(a-1)
    spec["overlays"] = [
        {"kind": "comment", "text": "댓글 하나", "start": 0, "end": 2, "x": 100, "y": 900}
    ]
    return job, db.add_revision(job, spec=spec, approved=True)


def variety_job(db: TDB) -> tuple[dict, dict]:
    job = db.add_job(
        status="inspect",
        format="variety",
        preset_version="variety-1080-v1",
        source_start_sec=5.0,
        segment_len_sec=20,
        source_meta=META,
    )
    db.add_asset(job, "source", duration_sec=18.0)
    spec = variety_spec()
    spec["reactions"] = [{"start": 1, "end": 2.5, "text": "(뭐야?)", "x": 200, "y": 700}]
    return job, db.add_revision(job, spec=spec, approved=True)


def shopping_job(db: TDB) -> tuple[dict, dict]:
    job, rev, _ = review_shop(db)
    narr = [db.add_asset(job, "narration")["id"] for _ in range(4)]
    rev["spec"]["voice"] = {"narration_asset_ids": narr}
    rev["approved_at"] = _now()
    return job, rev


MAKERS = {"category": category_job, "variety": variety_job, "shopping": shopping_job}


def ja_text(ko: str) -> str:
    return f"日本語:{ko}"


def reply(fmt: str, ko_spec: dict, change: Any = None) -> SimpleNamespace:
    items = [
        {"path": p, "text": ja_text(t)} for p, t in translate.text_slots(fmt, ko_spec) if t.strip()
    ]
    if change is not None:
        change(items)
    block = SimpleNamespace(
        type="tool_use", name=translate.TOOL_NAME, input={"translations": items}, id="t1"
    )
    return SimpleNamespace(stop_reason="tool_use", content=[block])


def post(api, auth, job: dict, rev_id: str, k: str = "tr-1", **over: Any) -> httpx.Response:
    body = {"revision_id": rev_id, "target_lang": "ja", **over}
    return api.post(
        f"{URL}/{job['id']}/translate", json=body, headers={**auth, "Idempotency-Key": k}
    )


def derived(api, auth, db: TDB, claude, fmt: str = "category") -> tuple[dict, dict, dict]:
    job, ko = MAKERS[fmt](db)
    claude.replies = [reply(fmt, ko["spec"])]
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 201, r.text
    ja = next(x for x in db.revisions if x["id"] == job["current_ja_revision_id"])
    return job, ko, ja


def put_ja(
    api, auth, job: dict, spec: dict, base_no: int = 1, base_updated_at: str | None = None
) -> httpx.Response:
    return api.put(
        f"{URL}/{job['id']}/revision",
        params={"lang": "ja"},
        json={
            "spec": spec,
            "base_rev_no": base_no,
            "base_updated_at": base_updated_at or cur_updated_at(api, auth, job["id"], "ja"),
        },
        headers=auth,
    )


def approve_ja(api, auth, job: dict, rev_no: int = 1) -> httpx.Response:
    return api.post(
        f"{URL}/{job['id']}/revision/approve", json={"rev_no": rev_no, "lang": "ja"}, headers=auth
    )


def codes(r: Any, key: str = "errors") -> list[str]:
    body = r if isinstance(r, dict) else r.json()
    return [e["code"] for e in body[key]]


# --- J3 경로 상수 ------------------------------------------------------------------


def test_text_paths_fixed():
    assert translate.TEXT_PATHS == {
        "category": ("header.lines[]", "hook.text", "items[].text", "overlays[].text"),
        "variety": ("header.lines[]", "subtitles[].text", "reactions[].text"),
        "shopping": ("script[].text", "cta.text"),
    }


@pytest.mark.parametrize(
    ("ja", "want"),
    [("三倍", {"3"}), ("二十三個", {"23"}), ("三万五千円", {"35000"}), ("十万円", {"100000"}),
     ("半額", set()), ("半分", set()), ("５％", {"5"})],
)  # fmt: skip
def test_kanji_number_tokens(ja, want):
    assert translate.numbers(ja) == want


@pytest.mark.parametrize(
    ("ko", "ja", "ok"),
    [("3배 빨라요", "三倍速い", True), ("빨라요", "三倍速い", False),
     ("빨라요", "十回使える", False),
     ("좋아요", "半額です", False), ("반값이에요", "半額です", True), ("좋아요", "効果あり", False),
     ("효과 있어요", "効果あり", True), ("좋아요", "送料無料", False),
     ("좋아요", "最安です", False),
     ("좋아요", "全額返金", False), ("좋아요", "十分です", True),
     ("좋아요", "一回使ってみて", True), ("좋아요", "一度だけ一緒に", True),
     ("좋아요", "三千円です", False)],
)  # fmt: skip
def test_parse_rejects_new_kanji_numbers_and_claims(ko, ja, ok):
    slots = [("hook.text", ko)]
    out = {"translations": [{"path": "hook.text", "text": ja}]}
    if ok:
        assert translate.parse(out, slots) == {"hook.text": ja}
    else:
        with pytest.raises(translate.TranslateFailed):
            translate.parse(out, slots)


def test_numbers_nfkc_and_commas():
    assert translate.numbers("３個で10,000円") == {"3", "10000"}
    assert translate.numbers("1.5배") == {"1.5"}


# --- 파생(J3·J6) -----------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["category", "variety", "shopping"])
def test_derive_keeps_non_text_fields(api, auth, db, claude, fmt):
    job, ko = MAKERS[fmt](db)
    ko_before = copy.deepcopy(ko["spec"])
    status = job["status"]
    claude.replies = [reply(fmt, ko["spec"])]
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    rev = body["revision"]
    assert rev["rev_no"] == 1 and rev["approved_at"] is None and rev["origin"] == "ai_draft"
    assert rev["derived_from"] == ko["id"] and body["translate_count"] == 1
    assert rev["validation"]["errors"] == [], rev["validation"]
    spec = rev["spec"]
    assert spec["lang"] == "ja"
    for path, text in translate.text_slots(fmt, ko_before):
        got = dict(translate.text_slots(fmt, spec))[path]
        assert got == (ja_text(text) if text.strip() else text)
    # J3 경로·음성·서버 값 밖은 ko와 같다(컷·구도·마스크·시각·좌표·kind·style)
    assert translate.locked_errors(fmt, spec, ko_before) == []
    assert translate._mask(fmt, spec) == translate._mask(fmt, ko_before)
    # J6 녹음 비움·ja TTS
    if fmt == "category":
        assert "audio_asset_id" not in spec["hook"]
        assert spec["hook"]["tts"]["voice"].startswith("ja-")
    if fmt == "shopping":
        assert spec["voice"] == {"tts": {"voice": translate.JA_TTS_VOICE, "rate": "+0%"}}
        assert spec["disclosure"] == {"text": "PR"}
    # 원본·작업 상태 불변
    assert ko["spec"] == ko_before and job["status"] == status
    assert job["current_revision_id"] == ko["id"] and job["ai_draft_count"] == 0
    assert job["translate_requests"][0]["kind"] == "translate"


@pytest.mark.parametrize("fmt", ["category", "variety", "shopping"])
def test_claude_receives_only_ko_texts(api, auth, db, claude, fmt):
    job, ko = MAKERS[fmt](db)
    claude.replies = [reply(fmt, ko["spec"])]
    assert post(api, auth, job, ko["id"]).status_code == 201
    call = claude.calls[0]
    blocks = call["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["text"]  # 이미지 없음
    assert db.storage_gets == []
    data = json.loads(
        blocks[0]["text"].split("<untrusted_data>\n", 1)[1].split("\n</untrusted_data>", 1)[0]
    )
    want = [[p, t] for p, t in translate.text_slots(fmt, ko["spec"]) if t.strip()]
    assert [[x["path"], x["text"]] for x in data["texts"]] == want
    dumped = json.dumps(call, ensure_ascii=False)
    for a in db.assets:
        assert a["id"] not in dumped  # 자산 ID·녹음 참조 없음
    assert call["tool_choice"] == {"type": "tool", "name": translate.TOOL_NAME}


# --- 번역 모의 응답(J9) ------------------------------------------------------------


def test_path_mismatch_retries_once_then_502(api, auth, db, claude):
    job, ko = category_job(db)

    def swap(items: list) -> None:
        items[0]["path"], items[1]["path"] = items[1]["path"], items[0]["path"]

    claude.replies = [reply("category", ko["spec"], swap)]
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 502 and r.json()["code"] == "UPSTREAM_ERROR"
    assert len(claude.calls) == 2
    assert job["translate_requests"][0]["status"] == "failed" and job["translate_count"] == 1
    assert job["current_ja_revision_id"] is None


def test_count_mismatch_is_502(api, auth, db, claude):
    job, ko = category_job(db)
    claude.replies = [reply("category", ko["spec"], lambda items: items.pop())]
    assert post(api, auth, job, ko["id"]).status_code == 502


def test_added_number_retried_then_ok(api, auth, db, claude):
    job, ko = category_job(db)

    def add_number(items: list) -> None:
        items[0]["text"] += " ３割引"

    claude.replies = [reply("category", ko["spec"], add_number), reply("category", ko["spec"])]
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 201, r.text
    assert len(claude.calls) == 2


def test_added_claim_twice_502(api, auth, db, claude):
    job, ko = category_job(db)

    def add_claim(items: list) -> None:
        items[0]["text"] += " 半額で効果抜群"

    claude.replies = [reply("category", ko["spec"], add_claim)]
    assert post(api, auth, job, ko["id"]).status_code == 502
    assert len(claude.calls) == 2


def test_added_number_twice_502(api, auth, db, claude):
    job, ko = category_job(db)

    def add_number(items: list) -> None:
        items[-1]["text"] += "100円"

    claude.replies = [reply("category", ko["spec"], add_number)]
    assert post(api, auth, job, ko["id"]).status_code == 502


def test_existing_ja_edit_kept_new_rev_no(api, auth, db, claude):
    job, ko, ja1 = derived(api, auth, db, claude)
    db.jobs[0]["translate_requests"][0]["created_at"] = "2026-01-01T00:00:00+00:00"
    claude.replies = [reply("category", ko["spec"])]
    r = post(api, auth, job, ko["id"], k="tr-2")
    assert r.status_code == 201 and r.json()["revision"]["rev_no"] == 2
    assert ja1 in db.revisions and job["current_ja_revision_id"] != ja1["id"]


# --- 입력·상태·카운터 -------------------------------------------------------------


def test_unapproved_or_past_ko_400_without_call(api, auth, db, claude):
    job, ko = category_job(db)
    ko["approved_at"] = None
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 400 and r.json()["field"] == "revision_id"
    ko["approved_at"] = _now()
    db.add_revision(job, rev_no=2, approved=True)  # 현재가 rev2로 → rev1은 과거 승인본
    assert post(api, auth, job, ko["id"]).status_code == 400
    assert claude.calls == [] and job["translate_count"] == 0


def test_target_lang_must_be_ja(api, auth, db, claude):
    job, ko = category_job(db)
    assert post(api, auth, job, ko["id"], target_lang="ko").status_code in (400, 422)


def test_ja_rendering_409(api, auth, db, claude):
    job, ko = category_job(db)
    db.runs.append(
        {
            "id": "r1",
            "job_id": job["id"],
            "workspace_id": job["workspace_id"],
            "lang": "ja",
            "status": "running",
        }
    )
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 409 and claude.calls == []


def test_separate_counter_and_key_space(api, auth, db, claude):
    job, ko = category_job(db)
    job["ai_draft_count"] = 3  # AI 초안 상한 도달이어도 번역은 별도
    job["ai_draft_requests"] = [{"key": "tr-1", "status": "done", "created_at": _now()}]
    claude.replies = [reply("category", ko["spec"])]
    r = post(api, auth, job, ko["id"])  # AI 초안에 쓴 키와 같은 이름도 별도 공간
    assert r.status_code == 201 and r.json()["replay"] is False
    assert job["ai_draft_count"] == 3 and job["translate_count"] == 1


def test_replay_same_key_200_no_new_call(api, auth, db, claude):
    job, ko, ja = derived(api, auth, db, claude)
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 200 and r.json()["replay"] is True
    assert r.json()["revision"]["id"] == ja["id"] and len(claude.calls) == 1
    assert job["translate_count"] == 1


def test_rate_limit_and_quota(api, auth, db, claude):
    job, ko, _ = derived(api, auth, db, claude)
    r = post(api, auth, job, ko["id"], k="tr-2")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"
    job["translate_requests"][0]["created_at"] = "2026-01-01T00:00:00+00:00"
    job["translate_count"] = 3
    r = post(api, auth, job, ko["id"], k="tr-3")
    assert r.status_code == 429 and r.json()["code"] == "QUOTA_EXCEEDED"


def test_no_key_503_without_reserve(mock_supabase, jwks_payload, db, claude, auth):
    _routes(mock_supabase, db)
    job, ko = category_job(db)
    with base._client(mock_supabase, jwks_payload, db) as c:
        r = post(c, auth, job, ko["id"])
    assert r.status_code == 503 and db.rpc_calls == []


def test_no_key_replays_done_request_only(mock_supabase, jwks_payload, db, claude, key, auth):
    _routes(mock_supabase, db)
    job, ko = category_job(db)
    claude.replies = [reply("category", ko["spec"])]
    with base._client(mock_supabase, jwks_payload, db, anthropic_api_key=key) as c:
        first = post(c, auth, job, ko["id"])
    assert first.status_code == 201
    calls = list(db.rpc_calls)
    with base._client(mock_supabase, jwks_payload, db) as c:  # 키 미설정
        r = post(c, auth, job, ko["id"])
        assert r.status_code == 200 and r.json()["replay"] is True
        assert r.json()["revision"]["id"] == first.json()["revision"]["id"]
        assert post(c, auth, job, ko["id"], k="tr-new").status_code == 503
        job["translate_requests"].append({"key": "tr-bad", "status": "failed"})
        assert post(c, auth, job, ko["id"], k="tr-bad").status_code == 502
    assert db.rpc_calls == calls and len(claude.calls) == 1  # 예약·호출 없음


def test_missing_idempotency_key_400(api, auth, db, claude):
    job, ko = category_job(db)
    r = api.post(
        f"{URL}/{job['id']}/translate",
        json={"revision_id": ko["id"], "target_lang": "ja"},
        headers=auth,
    )
    assert r.status_code == 400


# --- 편집 가드(J7) -----------------------------------------------------------------


def test_put_text_and_voice_ok(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["hook"]["text"] = "直した"
    spec["hook"]["tts"]["rate"] = "+30%"
    r = put_ja(api, auth, job, spec)
    assert r.status_code == 200, r.text
    assert ja["spec"]["hook"]["text"] == "直した" and job["status"] == "review"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["shots"][0].update(scale=1.5),
        lambda s: s["items"][0].update(kind="emph"),
        lambda s: s["items"].append({**s["items"][0], "start": 10, "end": 10}),
        lambda s: s["overlays"][0].update(x=200),
    ],
)
def test_put_locked_field_400_not_saved(api, auth, db, claude, mutate):
    job, _, ja = derived(api, auth, db, claude)
    before = copy.deepcopy(ja["spec"])
    spec = copy.deepcopy(ja["spec"])
    mutate(spec)
    r = put_ja(api, auth, job, spec)
    assert r.status_code == 400 and "ja.locked_field" in codes(r), r.text
    assert ja["spec"] == before and "ja_save" not in db.rpc_calls


def test_put_locked_shopping_mask_and_array_length(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude, "shopping")
    spec = copy.deepcopy(ja["spec"])
    spec["cuts"][0]["masks"] = [{"x": 0, "y": 0, "w": 10, "h": 10}]
    assert "ja.locked_field" in codes(put_ja(api, auth, job, spec))
    spec = copy.deepcopy(ja["spec"])
    spec["script"].pop()
    assert put_ja(api, auth, job, spec).status_code == 400


def test_put_approved_ja_creates_new_rev(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    ja["approved_at"] = _now()
    r = put_ja(api, auth, job, copy.deepcopy(ja["spec"]))
    assert r.status_code == 200 and r.json()["revision"]["rev_no"] == 2
    assert r.json()["revision"]["derived_from"] == ja["derived_from"]


def test_l1_translate_response_has_updated_at(api, auth, db, claude):
    job, ko = MAKERS["category"](db)
    claude.replies = [reply("category", ko["spec"])]
    r = post(api, auth, job, ko["id"])
    assert r.status_code == 201, r.text
    ja = next(x for x in db.revisions if x["id"] == job["current_ja_revision_id"])
    assert same_ts(r.json()["revision"]["updated_at"], ja["updated_at"])


def test_l5_ja_consecutive_saves_then_stale_409(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    first = cur_updated_at(api, auth, job["id"], "ja")
    r1 = put_ja(api, auth, job, copy.deepcopy(ja["spec"]), base_updated_at=first)
    assert r1.status_code == 200, r1.text
    at = r1.json()["revision"]["updated_at"]
    r2 = put_ja(api, auth, job, copy.deepcopy(ja["spec"]), base_updated_at=at)
    assert r2.status_code == 200, r2.text
    r3 = put_ja(api, auth, job, copy.deepcopy(ja["spec"]), base_updated_at="2000-01-01T00:00:00Z")
    assert r3.status_code == 409


def test_l3_ja_approved_stale_base_409(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    ja["approved_at"] = _now()
    r = put_ja(api, auth, job, copy.deepcopy(ja["spec"]), base_updated_at="2000-01-01T00:00:00Z")
    assert r.status_code == 409 and job["current_ja_revision_id"] == ja["id"]


# --- 승인·음성·내용 규칙(J6·J10) --------------------------------------------------------


def test_approve_ja_ok_job_state_unchanged(api, auth, db, claude):
    job, ko, ja = derived(api, auth, db, claude)
    r = approve_ja(api, auth, job)
    assert r.status_code == 200, r.text
    assert ja["approved_at"] is not None and job["status"] == "review"
    assert ko["approved_at"] is not None and "approve" not in db.rpc_calls


def test_ko_recording_in_ja_blocks_approve(api, auth, db, claude):
    job, ko, ja = derived(api, auth, db, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["hook"] = {"text": spec["hook"]["text"], "audio_asset_id": "a-1"}  # ko 녹음
    r = put_ja(api, auth, job, spec)
    assert r.status_code == 200 and "ja.voice_from_ko" in codes(r.json()["revision"]["validation"])
    r = approve_ja(api, auth, job)
    assert r.status_code == 400 and "ja.voice_from_ko" in codes(r)


def test_ko_voice_in_ja_tts_blocks(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["hook"]["tts"]["voice"] = "ko-KR-SunHiNeural"
    put_ja(api, auth, job, spec)
    assert "hook.tts.voice_lang" in codes(approve_ja(api, auth, job))


def test_shopping_ko_narration_in_ja_blocks(api, auth, db, claude):
    job, ko, ja = derived(api, auth, db, claude, "shopping")
    spec = copy.deepcopy(ja["spec"])
    spec["voice"] = copy.deepcopy(ko["spec"]["voice"])
    put_ja(api, auth, job, spec)
    assert "ja.voice_from_ko" in codes(approve_ja(api, auth, job))


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("確認[確認必要]", "ja.unverified"),
        ("[확인 필요] 문구", "ja.unverified"),
        ("毎日のサプリ", "ja.banned_category"),
    ],
)
def test_ja_content_rules_block_approve(api, auth, db, claude, text, code):
    job, _, ja = derived(api, auth, db, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["items"][0]["text"] = text
    put_ja(api, auth, job, spec)
    r = approve_ja(api, auth, job)
    assert r.status_code == 400 and code in codes(r)


def test_ja_banned_phrase_is_warning(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    spec = copy.deepcopy(ja["spec"])
    spec["hook"]["text"] = "今すぐチェック"
    r = put_ja(api, auth, job, spec)
    assert "ja.banned_phrase" in codes(r.json()["revision"]["validation"], "warnings")
    assert approve_ja(api, auth, job).status_code == 200


def test_shopping_ja_confirm_mark_blocks(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude, "shopping")
    spec = copy.deepcopy(ja["spec"])
    spec["cta"]["text"] = "[確認必要] リンク"
    put_ja(api, auth, job, spec)
    assert "script.unverified" in codes(approve_ja(api, auth, job))


# --- 원본 변경(J8)·상태 409 -----------------------------------------------------------


def test_get_ja_merges_source_changed_and_approve_blocked(api, auth, db, claude):
    job, ko, ja = derived(api, auth, db, claude)
    r = api.get(f"{URL}/{job['id']}/revision", params={"lang": "ja"}, headers=auth)
    assert r.status_code == 200 and r.json()["revision"]["validation"]["errors"] == []
    db.add_revision(job, rev_no=2, approved=True)  # ko 새 승인본
    r = api.get(f"{URL}/{job['id']}/revision", params={"lang": "ja"}, headers=auth)
    assert "ja.source_changed" in codes(r.json()["revision"]["validation"])
    assert "ja.source_changed" not in codes(ja["validation"])  # 저장값과 별개
    r = approve_ja(api, auth, job)
    assert r.status_code == 400 and "ja.source_changed" in codes(r)
    assert ja["approved_at"] is None


def test_ko_unapproved_ja_put_and_approve_409(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    db.add_revision(job, rev_no=2)  # ko 편집 중(미승인)
    assert put_ja(api, auth, job, copy.deepcopy(ja["spec"])).status_code == 409
    assert approve_ja(api, auth, job).status_code == 409


def test_ja_rendering_blocks_put_and_approve(api, auth, db, claude):
    job, _, ja = derived(api, auth, db, claude)
    db.runs.append(
        {
            "id": "r1",
            "job_id": job["id"],
            "workspace_id": job["workspace_id"],
            "lang": "ja",
            "status": "queued",
        }
    )
    assert put_ja(api, auth, job, copy.deepcopy(ja["spec"])).status_code == 409
    assert approve_ja(api, auth, job).status_code == 409


def test_get_ja_404_when_none_and_ko_get_unchanged(api, auth, db, claude):
    job, ko = category_job(db)
    r = api.get(f"{URL}/{job['id']}/revision", params={"lang": "ja"}, headers=auth)
    assert r.status_code == 404
    r = api.get(f"{URL}/{job['id']}/revision", headers=auth)
    assert r.status_code == 200 and r.json()["revision"]["id"] == ko["id"]


def test_ko_approve_still_uses_ko_path(api, auth, db, claude):
    job = db.add_job(status="review")
    db.add_revision(job)
    r = api.post(f"{URL}/{job['id']}/revision/approve", json={"rev_no": 1}, headers=auth)
    assert r.status_code == 200 and "approve" in db.rpc_calls
