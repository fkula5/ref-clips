"""Warstwa magazynu plików. Teraz dysk lokalny; później można dodać S3/Backblaze.

W bazie zapisujemy wyłącznie ścieżki względne (klucze magazynu).
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app import config


class Storage(ABC):
    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Ścieżka lokalna pliku (dla ffmpeg/serwowania). Zdalne magazyny pobiorą plik do cache."""

    @abstractmethod
    def open_write(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def open_update(self, key: str) -> BinaryIO:
        """Otwiera istniejący (albo nowy) plik do zapisu w dowolnym miejscu, bez obcinania."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def size(self, key: str) -> int: ...


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

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free


storage = LocalStorage(config.DATA_DIR)
