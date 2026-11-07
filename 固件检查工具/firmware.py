"""Firmware image readers and address-aware comparison. No third-party packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import re
import struct
import zlib


class FirmwareError(ValueError):
    pass


@dataclass
class Segment:
    address: int
    data: bytes

    @property
    def end(self) -> int:
        return self.address + len(self.data)


@dataclass
class Firmware:
    path: Path
    kind: str
    file_size: int
    crc32: str
    sha256: str
    segments: list[Segment] = field(default_factory=list)
    target: str = "未知"
    version: str = "未发现"
    flash_capacity: int | None = None
    flash_used: int | None = None
    bin_unlocated: bool = False
    map_sections: list[tuple[str, int, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def image_size(self) -> int:
        if self.bin_unlocated:
            return self.file_size
        return sum(len(s.data) for s in self.segments)

    @property
    def address_range(self) -> str:
        if self.bin_unlocated:
            return "未确定（BIN 不含地址）"
        if not self.segments:
            return "无可定位的镜像数据"
        return f"0x{self.segments[0].address:08X} – 0x{max(s.end for s in self.segments)-1:08X}"


MACHINES = {3: "x86", 8: "MIPS", 20: "PowerPC", 40: "ARM", 62: "x86-64", 83: "AVR", 183: "AArch64", 243: "RISC-V"}


def _metadata(data: bytes, name: str) -> tuple[str, str]:
    sample = data[:4_000_000]
    texts = [name, sample.decode("latin1", errors="ignore")]
    target = "未知"
    version = "未发现"
    target_re = re.compile(r"\b(?:STM32[A-Z0-9]{4,}|ESP32[A-Z0-9-]*|NRF5[0-9A-Z]+|GD32[A-Z0-9]+|RP2040|CH32[A-Z0-9]+)\b", re.I)
    version_re = re.compile(r"\b(?:firmware[_ -]?version|fw[_ -]?ver(?:sion)?|version)\s*[:= ]\s*(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][a-z0-9.]+)?)", re.I)
    for value in texts:
        if target == "未知" and (m := target_re.search(value)):
            target = m.group(0).upper()
        if version == "未发现" and (m := version_re.search(value)):
            version = m.group(1)
    return target, version


def _merge(segments: list[Segment]) -> list[Segment]:
    segments.sort(key=lambda s: s.address)
    result: list[Segment] = []
    for seg in segments:
        if not seg.data:
            continue
        if result and seg.address < result[-1].end:
            raise FirmwareError(f"镜像地址重叠：0x{seg.address:X}")
        if result and seg.address == result[-1].end:
            result[-1].data += seg.data
        else:
            result.append(seg)
    return result


def _hex(data: bytes) -> list[Segment]:
    upper = 0
    eof = False
    pieces: list[Segment] = []
    for line_no, raw in enumerate(data.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if eof:
            raise FirmwareError(f"HEX 第 {line_no} 行：EOF 后还有记录")
        if not line.startswith(b":"):
            raise FirmwareError(f"HEX 第 {line_no} 行：缺少冒号")
        try:
            record = bytes.fromhex(line[1:].decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            raise FirmwareError(f"HEX 第 {line_no} 行：非十六进制内容") from None
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 0xFF:
            raise FirmwareError(f"HEX 第 {line_no} 行：长度或校验和错误")
        count, offset, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        payload = record[4:-1]
        if kind == 0:
            if offset + count > 0x10000:
                raise FirmwareError(f"HEX 第 {line_no} 行：记录跨越 64 KiB 边界")
            pieces.append(Segment(upper + offset, payload))
        elif kind == 1:
            if count or offset:
                raise FirmwareError(f"HEX 第 {line_no} 行：EOF 记录无效")
            eof = True
        elif kind == 2:
            if count != 2 or offset:
                raise FirmwareError(f"HEX 第 {line_no} 行：段地址记录无效")
            upper = int.from_bytes(payload, "big") << 4
        elif kind == 4:
            if count != 2 or offset:
                raise FirmwareError(f"HEX 第 {line_no} 行：线性地址记录无效")
            upper = int.from_bytes(payload, "big") << 16
        elif kind in (3, 5):
            if count != 4 or offset:
                raise FirmwareError(f"HEX 第 {line_no} 行：入口地址记录无效")
        else:
            raise FirmwareError(f"HEX 第 {line_no} 行：不支持记录类型 {kind}")
    if not eof:
        raise FirmwareError("HEX 缺少 EOF 记录")
    return _merge(pieces)


def _elf(data: bytes) -> tuple[list[Segment], str]:
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise FirmwareError("ELF 文件头无效")
    bits, endian = data[4], data[5]
    if bits not in (1, 2) or endian not in (1, 2):
        raise FirmwareError("不支持的 ELF 类别或字节序")
    order = "<" if endian == 1 else ">"
    header = order + ("HHIIIIIHHHHHH" if bits == 1 else "HHIQQQIHHHHHH")
    if len(data) < 16 + struct.calcsize(header):
        raise FirmwareError("ELF 文件头截断")
    h = struct.unpack_from(header, data, 16)
    machine, phoff, phentsize, phnum = h[1], h[4], h[8], h[9]
    if phnum == 0xFFFF:
        raise FirmwareError("暂不支持扩展 ELF 程序头数量")
    fmt = order + ("IIIIIIII" if bits == 1 else "IIQQQQQQ")
    size = struct.calcsize(fmt)
    if phentsize < size or phoff + phentsize * phnum > len(data):
        raise FirmwareError("ELF 程序头越界或截断")
    pieces = []
    for n in range(phnum):
        p = struct.unpack_from(fmt, data, phoff + n * phentsize)
        if bits == 1:
            typ, offset, vaddr, paddr, filesz = p[:5]
        else:
            typ, _, offset, vaddr, paddr, filesz = p[:6]
        if typ != 1 or not filesz:
            continue
        if offset + filesz > len(data):
            raise FirmwareError(f"ELF LOAD 段 {n} 超出文件")
        pieces.append(Segment(paddr or vaddr, data[offset:offset + filesz]))
    return _merge(pieces), MACHINES.get(machine, f"ELF e_machine={machine}")


def _map(data: bytes) -> tuple[list[tuple[str, int, int]], int | None, int | None]:
    text = data.decode("utf-8", errors="replace")
    sections = []
    capacity = None
    flash_regions = []
    keil_regions = []
    in_memory = False
    for line in text.splitlines():
        stripped = line.strip()
        keil = re.search(r"\bLoad Region\s+(\S+)\s+\(\s*Base:\s*0x([0-9a-fA-F]+)\s*,\s*Size:\s*0x([0-9a-fA-F]+)\s*,\s*Max:\s*0x([0-9a-fA-F]+)", line, re.I)
        if keil and re.search(r"(?:IROM|ROM|FLASH)", keil.group(1), re.I):
            keil_regions.append((keil.group(1), int(keil.group(2), 16), int(keil.group(3), 16), int(keil.group(4), 16)))
        if stripped == "Memory Configuration":
            in_memory = True
            continue
        if in_memory and (stripped == "Linker script and memory map" or stripped.startswith("Linker script")):
            in_memory = False
        if in_memory:
            m = re.match(r"^\s*(FLASH\w*|ROM\w*)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)", line, re.I)
            if m:
                start, length = int(m.group(2), 16), int(m.group(3), 16)
                capacity = (capacity or 0) + length
                flash_regions.append((start, start + length))
        m = re.match(r"^(\.[\w.$-]+)\s+0x([0-9a-fA-F]+)\s+0x([0-9a-fA-F]+)(?:\s|$)", line)
        if m:
            size = int(m.group(3), 16)
            if size:
                sections.append((m.group(1), int(m.group(2), 16), size))
    if keil_regions:
        sections.extend((f"Load Region {name}", base, size) for name, base, size, _ in keil_regions)
        limits = [maximum for _, _, _, maximum in keil_regions]
        keil_capacity = sum(limits) if all(0 < value < 0xFFFFFFFF for value in limits) else None
        return sections, keil_capacity, sum(size for _, _, size, _ in keil_regions)
    intervals = sorted((max(start, addr), min(end, addr + size))
                       for _, addr, size in sections for start, end in flash_regions
                       if max(start, addr) < min(end, addr + size))
    used = 0
    last_end = 0
    for start, end in intervals:
        used += max(0, end - max(start, last_end))
        last_end = max(last_end, end)
    return sections, capacity, used if flash_regions else None


def load_bytes(data: bytes, name: str | Path, bin_base: int | None = 0) -> Firmware:
    path = Path(name)
    kind = path.suffix.lower().lstrip(".")
    if kind not in ("bin", "hex", "ihx", "elf", "axf", "out", "map"):
        raise FirmwareError(f"不支持的文件类型：{path.suffix}")
    target, version = _metadata(data, path.name)
    result = Firmware(path, kind.upper(), len(data), f"{zlib.crc32(data):08X}", hashlib.sha256(data).hexdigest(), target=target, version=version)
    if kind == "bin":
        if bin_base is None:
            result.bin_unlocated = True
            result.notes.append("BIN 本身不含加载地址；工程扫描无法推断基址。")
            return result
        if not 0 <= bin_base <= 0xFFFFFFFF:
            raise FirmwareError("BIN 基址必须在 0x00000000 到 0xFFFFFFFF 之间")
        result.segments = [Segment(bin_base, data)] if data else []
        result.notes.append("BIN 地址由输入基址决定；文件本身不包含地址信息。")
    elif kind in ("hex", "ihx"):
        result.segments = _hex(data)
    elif kind in ("elf", "axf", "out"):
        result.segments, arch = _elf(data)
        result.target = f"{target} ({arch})" if target != "未知" else arch
        result.notes.append("ELF 地址与占用依据 PT_LOAD 文件数据；不计入仅在 RAM 中分配的 BSS。")
    else:
        result.map_sections, result.flash_capacity, result.flash_used = _map(data)
        result.notes.append("map 文件仅提供链接布局；无完整镜像字节，不能进行字节级比较。")
        if result.flash_capacity:
            result.notes.append("容量来自链接器配置的区域上限，不一定等于芯片物理 Flash 总容量。")
    if result.segments and (result.target == "未知" or result.version == "未发现" or kind in ("elf", "axf", "out")):
        sample = bytearray()
        for seg in result.segments:
            sample.extend(seg.data[:4_000_000 - len(sample)])
            if len(sample) >= 4_000_000:
                break
        image_target, image_version = _metadata(bytes(sample), "")
        if image_target != "未知" and target == "未知":
            result.target = f"{image_target} ({arch})" if kind in ("elf", "axf", "out") else image_target
        if result.version == "未发现":
            result.version = image_version
    return result


def load(path: str | Path, bin_base: int | None = 0) -> Firmware:
    path = Path(path)
    return load_bytes(path.read_bytes(), path, bin_base)


@dataclass
class Change:
    start: int
    end: int  # exclusive
    kind: str
    before: bytes
    after: bytes

    @property
    def size(self) -> int:
        return self.end - self.start


def compare(a: Firmware, b: Firmware, limit: int = 10000) -> tuple[list[Change], dict[str, int], bool]:
    if not a.segments or not b.segments:
        raise FirmwareError("比较需要两个含地址数据的 BIN、HEX 或 ELF 文件")
    boundaries = sorted({point for s in a.segments + b.segments for point in (s.address, s.end)})
    changes: list[Change] = []
    totals = {"added": 0, "removed": 0, "modified": 0}
    truncated = False
    ai = bi = 0
    active: Change | None = None

    def flush() -> None:
        nonlocal active, truncated
        if active is not None:
            if len(changes) < limit:
                changes.append(active)
            else:
                truncated = True
            active = None

    for left, right in zip(boundaries, boundaries[1:]):
        while ai < len(a.segments) and a.segments[ai].end <= left:
            ai += 1
        while bi < len(b.segments) and b.segments[bi].end <= left:
            bi += 1
        sa = a.segments[ai] if ai < len(a.segments) and a.segments[ai].address <= left else None
        sb = b.segments[bi] if bi < len(b.segments) and b.segments[bi].address <= left else None
        if sa is None and sb is None:
            flush()
            continue
        for pos in range(left, right, 4096):
            end = min(pos + 4096, right)
            before = sa.data[pos - sa.address:end - sa.address] if sa else b""
            after = sb.data[pos - sb.address:end - sb.address] if sb else b""
            for i in range(end - pos):
                x = before[i:i + 1]
                y = after[i:i + 1]
                kind = "added" if not x else "removed" if not y else "modified" if x != y else "same"
                if kind == "same":
                    flush()
                    continue
                totals[kind] += 1
                address = pos + i
                if active and active.kind == kind and active.end == address:
                    active.end += 1
                    active.before += x[: max(0, 16 - len(active.before))]
                    active.after += y[: max(0, 16 - len(active.after))]
                else:
                    flush()
                    active = Change(address, address + 1, kind, x, y)
    flush()
    return changes, totals, truncated
