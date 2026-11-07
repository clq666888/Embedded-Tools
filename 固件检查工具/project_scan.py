"""Find firmware artifacts in a folder or ZIP without extracting archive contents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable
import os
import threading
import time
import zipfile

from firmware import Firmware, FirmwareError, load_bytes


EXTENSIONS = {".bin", ".hex", ".ihx", ".elf", ".axf", ".out", ".map"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".idea", ".vs"}
MAX_FILES = 3000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


@dataclass
class Artifact:
    name: str
    firmware: Firmware | None = None
    error: str = ""


@dataclass
class ScanResult:
    source: Path
    artifacts: list[Artifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0
    cancelled: bool = False

    @property
    def valid(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.firmware]


class _Cancelled(Exception):
    pass


def _read_chunks(stream, cancel: threading.Event | None) -> bytes:
    chunks = []
    while True:
        if cancel and cancel.is_set():
            raise _Cancelled
        part = stream.read(1024 * 1024)
        if not part:
            return b"".join(chunks)
        chunks.append(part)


class ScanSession:
    """Retains the traversal position so a cancelled scan can continue."""

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source).resolve()
        if not self.source.exists():
            raise FileNotFoundError(self.source)
        if self.source.is_dir():
            self.kind = "folder"
        elif self.source.is_file() and self.source.suffix.lower() == ".zip":
            self.kind = "zip"
        elif self.source.is_file() and self.source.suffix.lower() in EXTENSIONS:
            self.kind = "file"
        else:
            raise FirmwareError("请选择工程文件夹、ZIP 或支持的固件文件")
        self.result = ScanResult(self.source)
        self.pending_dirs = [self.source] if self.kind == "folder" else []
        self.pending_files: list[tuple[str, Path]] = []
        self.zip_index = 0
        self.total = 0
        self.found = 0
        self.scanned_dirs = 0
        self.finished = False

    def _record(self, artifact: Artifact, on_artifact: Callable[[int, Artifact], None] | None) -> None:
        index = len(self.result.artifacts)
        self.result.artifacts.append(artifact)
        if on_artifact:
            on_artifact(index, artifact)

    def _add_file(self, name: str, stream, size: int, cancel: threading.Event | None,
                  on_artifact: Callable[[int, Artifact], None] | None = None) -> bool:
        if size > MAX_FILE_BYTES or self.total + size > MAX_TOTAL_BYTES:
            self.result.skipped += 1
            return True
        try:
            data = _read_chunks(stream, cancel)
            if cancel and cancel.is_set():
                raise _Cancelled
            self.total += len(data)
            self._record(Artifact(name, load_bytes(data, name, None)), on_artifact)
        except _Cancelled:
            return False
        except (OSError, RuntimeError, zipfile.BadZipFile, FirmwareError, ValueError) as exc:
            self._record(Artifact(name, error=str(exc)), on_artifact)
        return True

    def run(self, cancel: threading.Event | None = None,
            progress: Callable[[int, int], None] | None = None,
            on_artifact: Callable[[int, Artifact], None] | None = None) -> ScanResult:
        if self.finished:
            return self.result
        self.result.cancelled = False
        last_progress = 0.0

        def report(force: bool = False) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if progress and (force or now - last_progress >= 0.25):
                progress(self.scanned_dirs, self.found)
                last_progress = now

        if self.kind == "folder":
            while self.pending_dirs or self.pending_files:
                if cancel and cancel.is_set():
                    self.result.cancelled = True
                    break
                if self.pending_files:
                    name, path = self.pending_files[-1]
                    if self.found >= MAX_FILES:
                        self.result.warnings.append(f"超过 {MAX_FILES:,} 个候选文件，已停止扫描。")
                        self.finished = True
                        break
                    try:
                        with path.open("rb") as stream:
                            complete = self._add_file(name, stream, path.stat().st_size, cancel, on_artifact)
                    except OSError as exc:
                        self._record(Artifact(name, error=str(exc)), on_artifact)
                        complete = True
                    if not complete:
                        self.result.cancelled = True
                        break
                    self.pending_files.pop()
                    self.found += 1
                    report()
                else:
                    folder = self.pending_dirs.pop()
                    try:
                        subdirs = []
                        files = []
                        with os.scandir(folder) as entries:
                            for item in entries:
                                if cancel and cancel.is_set():
                                    self.pending_dirs.append(folder)
                                    self.result.cancelled = True
                                    break
                                if item.is_dir(follow_symlinks=False) and item.name.lower() not in SKIP_DIRS:
                                    subdirs.append(Path(item.path))
                                elif item.is_file(follow_symlinks=False) and Path(item.name).suffix.lower() in EXTENSIONS:
                                    path = Path(item.path)
                                    files.append((path.relative_to(self.source).as_posix(), path))
                        if self.result.cancelled:
                            break
                        subdirs.sort(key=lambda path: path.name.casefold())
                        files.sort(key=lambda pair: pair[0].casefold())
                        self.pending_dirs.extend(reversed(subdirs))
                        self.pending_files.extend(reversed(files))
                    except OSError:
                        pass
                    self.scanned_dirs += 1
                    report()
            if not self.result.cancelled and not self.finished:
                self.finished = True
        elif self.kind == "zip":
            try:
                with zipfile.ZipFile(self.source) as archive:
                    infos = archive.infolist()
                    while self.zip_index < len(infos):
                        if cancel and cancel.is_set():
                            self.result.cancelled = True
                            break
                        info = infos[self.zip_index]
                        if info.is_dir() or PurePosixPath(info.filename).suffix.lower() not in EXTENSIONS:
                            self.zip_index += 1
                            continue
                        if self.found >= MAX_FILES:
                            self.result.warnings.append(f"超过 {MAX_FILES:,} 个候选文件，已停止扫描。")
                            self.finished = True
                            break
                        try:
                            with archive.open(info) as stream:
                                complete = self._add_file(info.filename, stream, info.file_size, cancel, on_artifact)
                        except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
                            self._record(Artifact(info.filename, error=str(exc)), on_artifact)
                            complete = True
                        if not complete:
                            self.result.cancelled = True
                            break
                        self.zip_index += 1
                        self.found += 1
                        report()
                    if not self.result.cancelled and not self.finished:
                        self.finished = True
            except zipfile.BadZipFile as exc:
                raise FirmwareError(f"ZIP 文件损坏：{exc}") from exc
        else:
            if cancel and cancel.is_set():
                self.result.cancelled = True
            else:
                with self.source.open("rb") as stream:
                    complete = self._add_file(self.source.name, stream, self.source.stat().st_size, cancel, on_artifact)
                if complete:
                    self.found = 1
                    self.finished = True
                else:
                    self.result.cancelled = True

        if self.finished:
            if self.result.skipped:
                self.result.warnings.append(f"跳过 {self.result.skipped} 个超出大小限制的文件（单个 128 MiB、合计 512 MiB）。")
            if not self.found:
                self.result.warnings.append("未找到 BIN、HEX、ELF 或 map 文件。可检查是否选中了工程根目录或包含编译产物的 ZIP。")
        report(force=True)
        return self.result


def scan_project(source: str | Path, cancel: threading.Event | None = None,
                 progress: Callable[[int, int], None] | None = None) -> ScanResult:
    return ScanSession(source).run(cancel, progress)
