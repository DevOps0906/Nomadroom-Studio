"""승인 리비전 spec → 렌더러 project 매핑(docs/05_DATA_MODEL.md#편집안-spec-필드).

경로 필드(source·output·hook_audio)는 spec에 없고 렌더러가 작업 폴더 안 고정 이름을 쓴다.
"""

from typing import Any

from production.errors import AudioMissing, RenderFailed
from production.overlays import normalize

PRESET_VERSION = "category-1080-v1"  # F9: 워커 렌더 프리셋. task·spec 값과 다르면 렌더하지 않는다


def to_project(spec: Any, lang: str | None) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise RenderFailed("spec 없음")
    try:
        hook = spec["hook"]
        if hook.get("tts") is not None:
            raise AudioMissing("TTS 훅은 task-030 전까지 지원하지 않음")  # F8
        if spec.get("preset_version") not in (None, PRESET_VERSION):
            raise RenderFailed("spec preset_version 불일치")
        if lang is not None and spec["lang"] != lang:
            raise RenderFailed("spec 언어 불일치")
        items = []
        for it in spec["items"]:
            row = [it["start"], it["end"], it["kind"], it["text"]]
            if it.get("y") is not None:
                row.append(it["y"])
            items.append(row)
        project_overlays = normalize(spec.get("overlays") or [], spec["duration"])
        return {
            "lang": spec["lang"],
            "header": list(spec["header"]["lines"]),
            "hook": hook["text"],
            "duration": spec["duration"],
            "shots": [[s["start"], s["end"], s["scale"], s["y"]] for s in spec["shots"]],
            "items": items,
            "overlays": project_overlays,
        }
    except KeyError, TypeError, AttributeError:
        raise RenderFailed("spec 형식 오류") from None
