import struct
import tempfile
import unittest
from pathlib import Path

from firmware import FirmwareError, compare, load


def record(address: int, kind: int, payload: bytes) -> bytes:
    raw = bytes([len(payload)]) + address.to_bytes(2, "big") + bytes([kind]) + payload
    return b":" + (raw + bytes([-sum(raw) & 0xFF])).hex().upper().encode() + b"\n"


class FirmwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def put(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_hex_extended_address_and_checksum(self) -> None:
        data = record(0, 4, b"\x08\x00") + record(0x10, 0, b"\x01\x02") + record(0, 1, b"")
        fw = load(self.put("a.hex", data))
        self.assertEqual(fw.address_range, "0x08000010 – 0x08000011")
        self.assertEqual(fw.image_size, 2)
        with self.assertRaisesRegex(FirmwareError, "校验和"):
            load(self.put("bad.hex", data.replace(b"0102", b"0103")))

    def test_hex_metadata_from_decoded_bytes(self) -> None:
        data = record(0, 0, b"version=1.2.3 STM32F103C8") + record(0, 1, b"")
        fw = load(self.put("image.hex", data))
        self.assertEqual(fw.version, "1.2.3")
        self.assertEqual(fw.target, "STM32F103C8")

    def test_elf_load_segment(self) -> None:
        ident = b"\x7fELF" + bytes([1, 1, 1]) + bytes(9)
        header = struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, 0, 52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack("<IIIIIIII", 1, 84, 0x08000000, 0x08000000, 3, 3, 5, 4)
        fw = load(self.put("a.elf", ident + header + ph + b"ABC"))
        self.assertEqual(fw.target, "ARM")
        self.assertEqual(fw.segments[0].data, b"ABC")

    def test_address_comparison(self) -> None:
        a = load(self.put("a.bin", b"ABCD"), 0x100)
        b = load(self.put("b.bin", b"BXZE"), 0x101)
        changes, totals, truncated = compare(a, b)
        self.assertEqual(totals, {"added": 1, "removed": 1, "modified": 2})
        self.assertEqual([(c.start, c.kind, c.size) for c in changes], [(0x100, "removed", 1), (0x102, "modified", 2), (0x104, "added", 1)])
        self.assertFalse(truncated)

    def test_map_capacity_and_sections(self) -> None:
        data = b"Memory Configuration\n\nName Origin Length Attributes\nFLASH 0x08000000 0x00040000 xr\nRAM 0x20000000 0x00010000 xrw\n\nLinker script and memory map\n.text 0x08000000 0x00000100\n"
        fw = load(self.put("board.map", data))
        self.assertEqual(fw.flash_capacity, 0x40000)
        self.assertEqual(fw.flash_used, 0x100)
        self.assertEqual(fw.map_sections, [(".text", 0x08000000, 0x100)])

    def test_keil_map_load_region(self) -> None:
        data = b"Memory Map of the image\nLoad Region LR_IROM1 (Base: 0x08000000, Size: 0x000059F0, Max: 0x00020000, ABSOLUTE)\nExecution Region ER_IROM1 (Base: 0x08000000, Size: 0x000059F0, Max: 0x00020000)\n"
        fw = load(self.put("bishe.map", data))
        self.assertEqual(fw.flash_used, 23024)
        self.assertEqual(fw.flash_capacity, 131072)
        self.assertEqual(fw.map_sections, [("Load Region LR_IROM1", 0x08000000, 23024)])


if __name__ == "__main__":
    unittest.main()
