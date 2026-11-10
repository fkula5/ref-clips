"""Only relative paths (storage keys) are stored in the DB."""
from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app import config


class Storage(ABC):
    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Local path of the file (for ffmpeg and serving). Remote stores would download it to a cache."""

    @abstractmethod
    def open_write(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def open_update(self, key: str) -> BinaryIO:
        """Opens an existing (or new) file for writing at any position, without truncating."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def iter_files(self, prefix: str) -> Iterator[tuple[str, int, float]]:
        """Files directly in the "directory" `prefix` as (key, size in bytes, mtime in epoch seconds):
        one directory pass, no per-file queries.
        """


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = root

    def local_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Ścieżka poza magazynem")
        return path

    def open_write(self, key: str) -> BinaryIO:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, "wb")

    def open_update(self, key: str) -> BinaryIO:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return open(path, "r+b")

    def exists(self, key: str) -> bool:
        return self.local_path(key).is_file()

    def delete(self, key: str | None) -> None:
        if key:
            self.local_path(key).unlink(missing_ok=True)

    def size(self, key: str) -> int:
        return self.local_path(key).stat().st_size

    def iter_files(self, prefix: str) -> Iterator[tuple[str, int, float]]:
        folder = self.local_path(prefix)
        if not folder.is_dir():
            return
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        yield f"{prefix.rstrip('/')}/{entry.name}", stat.st_size, stat.st_mtime
                except FileNotFoundError:  # file vanished while listing the directory
                    continue

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def total_bytes(self) -> int:
        return shutil.disk_usage(self.root).total


storage = LocalStorage(config.DATA_DIR)
