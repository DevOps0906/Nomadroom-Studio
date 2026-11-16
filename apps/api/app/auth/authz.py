"""인가 헬퍼: 경로의 리소스가 다른 워크스페이스(또는 없음)면 403이 아니라 404(존재 노출 방지)."""

import uuid

from app.errors import not_found


def not_found_if_other_workspace(
    resource_workspace_id: uuid.UUID | str | None, current_workspace_id: uuid.UUID
) -> None:
    if resource_workspace_id is None:
        raise not_found()
    try:
        resource_ws = uuid.UUID(str(resource_workspace_id))
    except ValueError as exc:
        raise not_found() from exc
    if resource_ws != current_workspace_id:
        raise not_found()
