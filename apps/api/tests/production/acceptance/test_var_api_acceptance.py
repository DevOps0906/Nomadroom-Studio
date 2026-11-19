# ruff: noqa: F401, F811
"""task-038 인수 테스트(API 쪽): 예능형 VAR-01·03·04(+VAR-05 회귀는 CAT 파일 재실행).

가짜 PostgREST·Storage(ProdDB)에 사용자 API·워커 API를 실제 라우터로 호출한다.
실제 ffmpeg 렌더는 워커 acceptance·실환경(scratchpad acc038)이 맡는다.
근거: tasks/plan-variety-shorts.md#인수 기준, docs/05_DATA_MODEL.md#예능형-spec.
"""

import copy

# fixture 재사용(ruff: 사용처는 pytest 주입)
from tests.production.acceptance.test_cat_api_acceptance import (  # noqa: F401
    api,
    auth,
    claim_render,
    db,
    make_asset_ready,
    post,
    put_spec,
    render_done,
    request_run,
)
from tests.production.test_jobs_api import CAND, URL, WS
from tests.production.test_render_runs import ProdDB
from tests.production.test_validation_variety import good as example_good
from tests.production.test_worker_production import (
    PREPARE_ITEMS,
    W,
    claim,
    finish,
    item,
    outputs,
    upload_all,
)

PRESET = "variety-1080-v1"
SEGMENT = 51.5


def example_spec() -> dict:
    """분석 문서 #2 컷 14개. 컷 3은 속도 1.0·길이 1.37초(task-038 재현 규칙, 컷별 속도 미지원)."""
    s = example_good()
    s["preset_version"] = PRESET
    s["source_start_sec"] = 0
    return s


def errs(resp, key: str = "errors") -> list[str]:
    return [e["code"] for e in resp.json()["revision"]["validation"][key]]


def variety_job(api, auth, db: ProdDB, key: str = "var-job") -> dict:
    db.candidates.append({"id": CAND, "workspace_id": WS}) if not db.candidates else None
    r = post(
        api,
        auth,
        "",
        headers={"Idempotency-Key": key},
        json={
            "title": "예능형 소재",
            "candidate_id": CAND,
            "format": "variety",
            "source_kind": "upload",
            "rights_confirmed": True,
            "source_start_sec": 0,
            "segment_len_sec": SEGMENT,
        },
    )
    assert r.status_code == 201, r.text
    job = r.json()["job"]
    assert job["format"] == "variety" and job["preset_version"] == PRESET
    return job


def prepared(api, auth, db: ProdDB, width: int = 1280, height: int = 720) -> dict:
    job = variety_job(api, auth, db)
    make_asset_ready(api, auth, db, job["id"], "source_upload", "video/mp4")
    assert post(api, auth, f"/{job['id']}/prepare").status_code == 202
    claim(api)
    items = [item("source", "video/mp4", duration_sec=SEGMENT), *PREPARE_ITEMS[1:]]
    ids = upload_all(db, outputs(api, "prepare", job["id"], items))
    meta = {"duration_sec": SEGMENT, "width": width, "height": height, "has_audio": True}
    assert (
        finish(api, "prepare", job["id"], status="done", asset_ids=ids, meta=meta).status_code
        == 200
    )
    return job


def save(api, auth, jid: str, spec: dict, base: int = 1):
    return put_spec(api, auth, jid, spec, base)


def approve(api, auth, jid: str, rev_no: int = 1):
    return post(api, auth, f"/{jid}/revision/approve", json={"rev_no": rev_no})


# === VAR-01: 예제 컷 14개 → 승인 → 렌더 요청 → 검수 완료 ==================================


def test_var01_fourteen_cuts_flow_to_done_and_task_carries_the_table(api, auth, db):
    job = prepared(api, auth, db)
    spec = example_spec()
    assert len(spec["cuts"]) == 14
    # 컷 3 규칙: 속도 필드가 없고 원본 길이 = 출력 길이 1.37
    c3 = spec["cuts"][2]
    assert round(c3["src_end"] - c3["src_start"], 2) == 1.37 and "speed" not in c3
    r = save(api, auth, job["id"], spec)
    assert r.status_code == 200, r.text
    assert errs(r) == [] and errs(r, "warnings") == ["cuts.short"]  # 컷 2(0.43초)만 경고
    ap = approve(api, auth, job["id"])
    assert ap.status_code == 200, ap.text
    rev_id = ap.json()["revision"]["id"]
    run = request_run(api, auth, job["id"], rev_id, "var-1").json()["render_run"]
    task = claim_render(api, run["id"])
    assert task["format"] == "variety" and task["preset_version"] == PRESET
    cuts = task["spec"]["cuts"]
    assert [(c["src_start"], c["src_end"]) for c in cuts] == [
        (c["src_start"], c["src_end"]) for c in spec["cuts"]
    ]  # 워커가 받는 컷 표 = 승인된 편집안
    total = sum(c["src_end"] - c["src_start"] for c in cuts)
    assert abs(total - 24.0) < 0.05  # 예제 컷 길이 합 24.0초(14컷)
    inputs = api.get(f"{W}/render/{run['id']}/inputs", headers=_w()).json()["inputs"]
    assert "hook_audio" not in {i["kind"] for i in inputs}  # 예능형은 훅 음성 없음
    render_done(api, db, run["id"])
    assert db.job(job["id"])["status"] == "inspect"
    done = post(api, auth, f"/{job['id']}/review/approve")
    assert done.status_code == 200 and done.json()["job"]["status"] == "done"


def _w():
    from tests.production.test_render_runs import wauth

    return wauth()


def test_var01_variety_job_rejects_hook_audio_upload(api, auth, db):
    job = prepared(api, auth, db)
    r = post(
        api,
        auth,
        f"/{job['id']}/uploads",
        json={"kind": "hook_audio", "size_bytes": 1024, "mime": "audio/wav"},
    )
    assert r.status_code == 400


# === VAR-03: 대사·펀치·반응 자막 동시, 제목 필수 ==============================================


def test_var03_line_punch_reaction_together_valid_and_header_required(api, auth, db):
    job = prepared(api, auth, db)
    spec = example_spec()
    spec["subtitles"] = [
        {"start": 1.0, "end": 2.6, "style": "line", "text": "대사 검정"},
        {"start": 3.0, "end": 4.6, "style": "punch", "text": "펀치 빨강"},
    ]
    spec["reactions"] = [{"start": 1.2, "end": 2.4, "text": "(나는 왜?)", "x": 200, "y": 700}]
    r = save(api, auth, job["id"], spec)
    assert r.status_code == 200 and errs(r) == []  # 반응이 대사와 겹쳐도 오류 아님
    saved = db.revisions[-1]["spec"] if hasattr(db, "revisions") else spec
    assert {s["style"] for s in saved["subtitles"]} == {"line", "punch"}
    assert saved["reactions"] and saved["header"]["lines"]
    bad = copy.deepcopy(spec)
    bad["header"]["lines"] = []
    r = save(api, auth, job["id"], bad, 1)
    assert r.status_code == 200 and "header.invalid" in errs(r)
    assert approve(api, auth, job["id"], 1).status_code == 400  # 제목 없으면 승인 불가


# === VAR-04: 막는 오류 / 경고만 ================================================================


def _blocked(api, auth, db, mutate, code, **dims):
    job = prepared(api, auth, db, **dims)
    spec = example_spec()
    mutate(spec)
    r = save(api, auth, job["id"], spec)
    assert r.status_code == 200, r.text
    assert code in errs(r), errs(r)
    ap = approve(api, auth, job["id"])
    assert ap.status_code == 400 and code in [e["code"] for e in ap.json()["errors"]]
    assert (
        request_run(api, auth, job["id"], "00000000-0000-0000-0000-000000000000", "x").status_code
        >= 400
    )


def test_var04_out_of_range_blocks_approve(api, auth, db):
    _blocked(api, auth, db, lambda s: s["cuts"][0].update(src_end=SEGMENT + 5), "cuts.out_of_range")


def test_var04_empty_area_blocks_approve(api, auth, db):
    _blocked(api, auth, db, lambda s: s["cuts"][0].update(x=900), "cuts.empty_area")


def test_var04_landscape_scale_one_is_empty_area(api, auth, db):
    """16:9 원본은 배율 1이면 띠 높이를 못 채운다."""
    _blocked(api, auth, db, lambda s: s["cuts"][0].update(scale=1.0, x=0, y=0), "cuts.empty_area")


def test_var04_subtitle_overlap_blocks_approve(api, auth, db):
    def mut(s):
        s["subtitles"][1]["start"] = 1.0

    _blocked(api, auth, db, mut, "subtitles.overlap")


def test_var04_cut_under_0_2s_blocks_approve(api, auth, db):
    def mut(s):
        c = s["cuts"][3]
        c["src_end"] = c["src_start"] + 0.19

    _blocked(api, auth, db, mut, "cuts.too_short")


def test_var04_short_cut_and_short_subtitle_are_warnings_only(api, auth, db):
    job = prepared(api, auth, db)
    spec = example_spec()
    c = spec["cuts"][3]
    c["src_end"] = c["src_start"] + 0.45  # 0.5초 미만 컷
    spec["subtitles"] = [
        {"start": 0.0, "end": 1.0, "style": "line", "text": "짧은 자막"}
    ]  # 1.4초 미만
    r = save(api, auth, job["id"], spec)
    assert r.status_code == 200 and errs(r) == []
    w = set(errs(r, "warnings"))
    assert {"cuts.short", "subtitles.short"} <= w
    assert approve(api, auth, job["id"]).status_code == 200  # 경고는 승인 가능


def test_var04_boundary_exactly_0_2s_cut_is_allowed(api, auth, db):
    job = prepared(api, auth, db)
    spec = example_spec()
    c = spec["cuts"][3]
    c["src_end"] = round(c["src_start"] + 0.2, 4)
    r = save(api, auth, job["id"], spec)
    assert "cuts.too_short" not in errs(r)
