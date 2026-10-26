import struct
import zlib
from pathlib import Path

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

def png(n):
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            u, v = (x + .5) / n, (y + .5) / n
            c = (22, 54, 92, 255) if .04 < u < .96 and .04 < v < .96 else (0, 0, 0, 0)
            if .23 < u < .77 and .27 < v < .73: c = (238, 244, 252, 255)
            if .29 < u < .71 and .33 < v < .67: c = (20, 104, 173, 255)
            if .31 < u < .69 and (.18 < v < .26 or .74 < v < .82): c = (86, 211, 191, 255)
            if .37 < u < .63 and (.43 < v < .47 or .53 < v < .57): c = (255, 255, 255, 255)
            row.extend(c)
        rows.append(bytes(row))
    return bytes.fromhex("89504E470D0A1A0A") + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")

sizes = (16, 32, 48, 64)
payload, entries = b"", []
offset = 6 + 16 * len(sizes)
for n in sizes:
    blob = png(n)
    entries.append(struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(blob), offset + len(payload)))
    payload += blob
Path(__file__).parent.joinpath("assets", "uart.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + payload)
