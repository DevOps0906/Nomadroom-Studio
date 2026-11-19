"""작업 폴더 경로 보안. 파일명은 워커 코드가 정하고, 작업 폴더 밖·절대 경로·`..`는 거부한다."""

import re
import shutil
import uuid
from pathlib import Path

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class UnsafePath(ValueError):
    pass


class WorkDir:
    """task 하나의 작업 폴더(`<root>/<task uuid>`). 다시 받은 task는 지우고 처음부터(F5)."""

    def __init__(self, root: Path, task_id: uuid.UUID) -> None:
        if not isinstance(task_id, uuid.UUID):
            raise UnsafePath("task id는 UUID여야 합니다.")
        self.root = Path(root).resolve()
        self.dir = (self.root / str(task_id)).resolve()

    def reset(self) -> None:
        self.remove()
        self.dir.mkdir(parents=True)

    def remove(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def path(self, *parts: str) -> Path:
        """작업 폴더 안의 경로. 각 부분은 단순 이름(구분자·드라이브·`..` 없음)만 허용."""
        if not parts:
            raise UnsafePath("빈 경로")
        for part in parts:
            if not isinstance(part, str) or not _SAFE_NAME.match(part) or ".." in part:
                raise UnsafePath("허용되지 않은 파일 이름")
        target = self.dir.joinpath(*parts).resolve()
        if not target.is_relative_to(self.dir) or target == self.dir:
            raise UnsafePath("작업 폴더 밖 경로")
        return target


def clean_root(root: Path) -> int:
    """시작 시 작업 루트의 하위 폴더를 모두 지운다(단일 워커 전제, 리뷰 반영 6). 지운 개수."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
            removed += 1
    return removed
