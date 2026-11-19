"""작업 실패·중단 예외. 메시지에는 URL·토큰·로컬 경로를 넣지 않는다(04_API.md W-09)."""


class TaskFailed(Exception):
    """W-09 failed로 보고할 실패. stage·code는 04_API.md W-09 허용 값."""

    def __init__(self, stage: str, code: str, detail: str = "") -> None:
        super().__init__(f"{stage}/{code}")
        self.stage, self.code, self.detail = stage, code, detail


class TextTooLong(TaskFailed):
    def __init__(self, detail: str = "") -> None:
        super().__init__("render", "text_too_long", detail)


class HookTooLong(TaskFailed):
    def __init__(self, detail: str = "") -> None:
        super().__init__("audio", "hook_too_long", detail)


class AudioMissing(TaskFailed):
    def __init__(self, detail: str = "") -> None:
        super().__init__("audio", "audio_missing", detail)


class RenderFailed(TaskFailed):
    def __init__(self, detail: str = "") -> None:
        super().__init__("render", "render_failed", detail)


class TaskCancelled(Exception):
    """API가 409(종료·다른 워커)로 응답 — 즉시 중단, finish를 보내지 않는다."""


class ApiCallError(Exception):
    """W-05~W-09 호출 실패(409 외). 메시지는 경로 이름·상태 코드만.
    status=HTTP 코드(네트워크 오류면 None)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TransferError(ApiCallError):
    """서명 URL 다운로드·업로드 실패(재발급 1회 후에도). 작업 실패로 보고한다."""
