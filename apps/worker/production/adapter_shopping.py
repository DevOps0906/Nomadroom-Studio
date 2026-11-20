"""쇼핑 승인 리비전 spec → 렌더 입력(shopping project) + 비신뢰 재검증 + 문장·컷 시간 배치.

규칙 정본은 서버 검증(apps/api/app/production/validation_shopping.py,
docs/05_DATA_MODEL.md#쇼핑-spec-필드). 워커는 같은 상한·거부 문자로 다시 확인하고 위반은
RenderFailed. 자산은 W-06이 준 asset_id 목록에서만 찾는다(R3: 주지 않은 id 거부).
컷의 source_upload id는 W-06 파생 source(parent_asset_id)로 바꾼다(R5, 시각은 파생 source 기준).
게시 문구는 만들지 않는다(R7, A-21 서버).
"""

import math
from typing import Any

from production.adapter_variety import _list, _num, _text, frame_of
from production.api import SignedUrl
from production.errors import AudioMissing, RenderFailed

PRESET_VERSION = "shopping-1080-v1"  # task-044 결정과 같은 값(F9)
LANGS = ("ko", "ja")  # ja는 task-050(별도 MP4·JP 글꼴·글자 단위 줄바꿈)
FPS = 30
TOL = 0.001
SRC_TOL = 0.05  # 파생 source 길이와 구간 끝 차이 허용(초, 예능형과 같음)
CANVAS_W, CANVAS_H = 1080, 1920
SENTENCES = 4
MAX_CUTS = 60
MAX_MASKS = 20
MAX_TEXT_CHARS = 200
MAX_IMAGE_SEC = 20.0  # 사진 컷 표시 길이 상한(가정)
MAX_TOTAL_SEC = 180.0  # 리뷰 반영 1: 총 내레이션(=출력) 길이 상한
MAX_CUT_ASSETS = 20  # 리뷰 반영 2: 컷 입력 서로 다른 자산 수(원본 10 + 사진 10)
MOTIONS = ("pan", "zoom", "none")
DEFAULT_MOTION = "zoom"  # 05 쇼핑 spec: image 컷 기본 zoom(가정)
# 팀장 결정(Q12): 표기 고정 문구. 다른 값이면 렌더하지 않는다
DISCLOSURE_TEXT = {"ko": "제휴 링크 포함", "ja": "PR"}


def _id(v: Any) -> str:
    if not isinstance(v, str) or not 1 <= len(v) <= 64:
        raise RenderFailed("spec 자산 id 오류")
    return v


def to_shopping_project(spec: Any, lang: str | None) -> dict[str, Any]:
    """spec → project(자산은 id만). 시간 배치는 실측 길이를 안 뒤 layout()이 한다."""
    if not isinstance(spec, dict):
        raise RenderFailed("spec 없음")
    if spec.get("preset_version") not in (None, PRESET_VERSION):
        raise RenderFailed("spec preset_version 불일치")
    if lang not in LANGS or spec.get("lang") not in (None, lang):
        raise RenderFailed("spec 언어 불일치")
    script = _list(spec, "script", SENTENCES)
    if len(script) != SENTENCES or not all(isinstance(s, dict) for s in script):
        raise RenderFailed("script 형식 오류")
    texts = [_text(s.get("text"), MAX_TEXT_CHARS) for s in script]
    cta, disclosure = spec.get("cta"), spec.get("disclosure")
    cta_text = _text(cta.get("text") if isinstance(cta, dict) else None, MAX_TEXT_CHARS)
    disc = disclosure.get("text") if isinstance(disclosure, dict) else None
    if disc != DISCLOSURE_TEXT[lang]:
        raise RenderFailed("표기 문구가 고정 값이 아님")

    raw_cuts = _list(spec, "cuts", MAX_CUTS)
    cuts = []
    for c in raw_cuts:
        if not isinstance(c, dict):
            raise RenderFailed("cut 형식 오류")
        s, e, scale, x, y = (_num(c.get(k)) for k in ("src_start", "src_end", "scale", "x", "y"))
        sentence = c.get("sentence")
        if isinstance(sentence, bool) or sentence not in range(1, SENTENCES + 1):
            raise RenderFailed("cut 문장 번호 오류")
        if s < -TOL or e - s < 1 / FPS - TOL:
            raise RenderFailed("cut 범위 오류")
        if not 1 <= scale <= 3:
            raise RenderFailed("cut 배율 오류")
        masks = []
        for m in _list(c, "masks", MAX_MASKS):
            if not isinstance(m, dict):
                raise RenderFailed("mask 형식 오류")
            mx, my, mw, mh = (_num(m.get(k)) for k in ("x", "y", "w", "h"))
            if (
                mx < -TOL
                or my < -TOL
                or mw <= 0
                or mh <= 0
                or mx + mw > CANVAS_W + TOL
                or my + mh > CANVAS_H + TOL
            ):
                raise RenderFailed("mask 범위 오류")
            masks.append((mx, my, mw, mh))
        motion = c.get("motion")
        if motion is not None:
            if not isinstance(motion, dict) or motion.get("type") not in MOTIONS:
                raise RenderFailed("motion 형식 오류")
            motion = motion["type"]
        cuts.append(
            {
                "asset_id": _id(c.get("source_asset_id")),
                "sentence": sentence,
                "src_start": max(s, 0.0),
                "src_end": e,
                "scale": scale,
                "x": x,
                "y": y,
                "masks": masks,
                "motion": motion,
            }
        )
    if {c["sentence"] for c in cuts} != set(range(1, SENTENCES + 1)):
        raise RenderFailed("컷 없는 문장")

    voice = spec.get("voice")
    if not isinstance(voice, dict):
        raise RenderFailed("voice 형식 오류")
    tts, ids = voice.get("tts"), voice.get("narration_asset_ids")
    if (tts is None) == (ids is None):
        raise RenderFailed("voice는 tts·narration_asset_ids 중 하나")
    if ids is not None:
        if not isinstance(ids, list) or len(ids) != SENTENCES:
            raise RenderFailed("문장별 녹음은 4개")
        ids = [_id(i) for i in ids]
        if len(set(ids)) != SENTENCES:
            raise RenderFailed("문장별 녹음 중복")
    elif not isinstance(tts, dict):
        raise RenderFailed("tts 형식 오류")
    source_audio = spec.get("source_audio", "mute")
    if source_audio not in ("mute", "duck"):
        raise RenderFailed("source_audio 오류")
    bgm = spec.get("bgm_asset_id")
    return {
        "lang": lang,
        "script": texts,
        "cta": cta_text,
        "disclosure": DISCLOSURE_TEXT[lang],
        "cuts": cuts,
        "tts": tts,
        "narration_ids": ids,
        "source_audio": source_audio,
        "bgm_id": _id(bgm) if bgm is not None else None,
    }


def bind_inputs(project: dict, inputs: list[SignedUrl]) -> dict[str, Any]:
    """R3·R5: spec이 참조하는 id를 W-06 입력에 묶는다. 주지 않은 id는 거부.
    반환 {cuts: [SignedUrl](컷 순서), narration: [SignedUrl]|None, bgm: SignedUrl|None}."""
    by_id = {str(s.asset_id): s for s in inputs}
    derived = {
        str(s.parent_asset_id): s for s in inputs if s.kind == "source" and s.parent_asset_id
    }
    cut_inputs = []
    for c in project["cuts"]:
        got = by_id.get(c["asset_id"])
        if got is not None and got.kind not in ("source", "image"):
            got = None
        got = got or derived.get(c["asset_id"])
        if got is None:
            raise RenderFailed("W-06이 주지 않은 컷 자산")
        if c["motion"] is not None and got.kind != "image":
            raise RenderFailed("motion은 사진 컷만")
        cut_inputs.append(got)
    if len({str(s.asset_id) for s in cut_inputs}) > MAX_CUT_ASSETS:
        raise RenderFailed("컷 자산 수 상한 초과")
    narration = None
    if project["narration_ids"] is not None:
        narration = [by_id.get(i) for i in project["narration_ids"]]
        if any(n is None or n.kind != "narration" for n in narration):
            raise AudioMissing("W-06이 주지 않은 녹음")
    bgm = None
    if project["bgm_id"] is not None:
        bgm = by_id.get(project["bgm_id"])
        if bgm is None or bgm.kind != "bgm":
            raise RenderFailed("W-06이 주지 않은 BGM")
    return {"cuts": cut_inputs, "narration": narration, "bgm": bgm}


def covered(scale: float, x: float, y: float, src_w: int, src_h: int) -> bool:
    """가로 맞춤 배치(폭 1080×scale, 중심 540+x·960+y)가 캔버스 전체를 덮는가(실제 크기)."""
    w = CANVAS_W * scale
    h = CANVAS_W * src_h / src_w * scale
    left, top = CANVAS_W / 2 + x - w / 2, CANVAS_H / 2 + y - h / 2
    return left <= TOL and top <= TOL and left + w >= CANVAS_W - TOL and top + h >= CANVAS_H - TOL


def sentence_frames(durations: list[float]) -> list[int]:
    """R8: 문장 경계 = 누적 실측 길이의 30fps 반올림. 반환 [B0=0, B1..B4]."""
    out, total = [0], 0.0
    for d in durations:
        if not math.isfinite(d) or d <= 0:
            raise RenderFailed("문장 음성 길이 오류")
        total += d
        out.append(frame_of(total))
    if any(b <= a for a, b in zip(out, out[1:], strict=False)):
        raise RenderFailed("문장 음성이 1프레임보다 짧음")
    if out[-1] > MAX_TOTAL_SEC * FPS:
        raise RenderFailed("총 내레이션 길이 상한 초과")
    return out


def layout(project: dict, bounds: list[int]) -> list[dict]:
    """문장 구간에 컷 길이를 맞춘다: 컷 원래 길이(문장 안 누적 프레임 격자)대로 놓고, 넘치면
    뒤 컷을 자르거나 빼고(trimmed·dropped), 모자라면 문장의 마지막 컷을 정지 프레임으로 늘린다
    (extended). 반환: 출력 순서(문장 순, 같은 문장은 spec 순) 컷 목록 + 프레임·조정 기록."""
    out = []
    for s in range(1, SENTENCES + 1):
        span = bounds[s] - bounds[s - 1]
        group = [(i, c) for i, c in enumerate(project["cuts"]) if c["sentence"] == s]
        used, cum, prev = 0, 0.0, 0
        for n, (i, c) in enumerate(group):
            cum += c["src_end"] - c["src_start"]
            natural = frame_of(cum) - prev
            prev += natural
            frames = min(natural, span - used)
            last = n == len(group) - 1
            if last and used + frames < span:
                frames = span - used
            adjust = (
                "dropped"
                if frames <= 0
                else "trimmed"
                if frames < natural
                else "extended"
                if frames > natural
                else None
            )
            out.append(
                {
                    **c,
                    "index": i,
                    "natural_frames": natural,
                    "frames": max(frames, 0),
                    "frame_start": bounds[s - 1] + used,
                    "adjust": adjust,
                }
            )
            used += max(frames, 0)
    return out
