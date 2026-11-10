"""
innoextract.py - Pure Python Inno Setup 6.7.0 extractor
Ported from https://github.com/UserUnknownFactor/innoextract_win
"""

import io
import lzma
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


SETUP_LOADER_MAGIC = b"rDlPtS"
ZLB_MAGIC = b"zlb\x1a"
BLOCK_SIZE = 4096


@dataclass
class FileEntry:
    destination: str
    location: int


@dataclass
class DataEntry:
    chunk_offset: int
    file_offset: int
    file_size: int
    chunk_size: int
    chunk_compressed: bool
    call_instruction_filter: bool


def read_u32(f): return struct.unpack("<I", f.read(4))[0]
def read_u64(f): return struct.unpack("<Q", f.read(8))[0]


def read_str(f) -> str:
    length = read_u32(f)
    if length == 0:
        return ""
    return f.read(length).decode("utf-16-le", errors="replace")


def find_offsets(data: bytes) -> tuple[int, int]:
    """Find header_offset and data_offset from PE RCDATA 11111."""
    pos = data.find(SETUP_LOADER_MAGIC)
    if pos == -1:
        raise RuntimeError("Setup loader magic not found")

    revision = struct.unpack_from("<I", data, pos + 12)[0]
    if revision == 2:
        header_offset = struct.unpack_from("<Q", data, pos + 40)[0]
        data_offset = struct.unpack_from("<Q", data, pos + 48)[0]
    else:
        header_offset = struct.unpack_from("<I", data, pos + 28)[0]
        data_offset = struct.unpack_from("<I", data, pos + 32)[0]

    # Validate: header should have "Inno Setup"
    if data[header_offset:header_offset + 10] != b"Inno Setup":
        header_offset, data_offset = data_offset, header_offset

    return header_offset, data_offset


def decompress_block(data: bytes, offset: int) -> tuple[bytes, int]:
    """Decompress a header block. Returns (decompressed_data, next_offset)."""
    # Block header: CRC(4) + StoredSize(u64) + Compressed(u8)
    stored_size = struct.unpack_from("<Q", data, offset + 4)[0]
    compressed = data[offset + 12]
    block_start = offset + 13

    # Read CRC-interleaved sub-blocks
    raw = bytearray()
    pos = block_start
    br = 0
    while br < stored_size:
        pos += 4; br += 4  # skip CRC
        cs = min(BLOCK_SIZE, stored_size - br)
        raw.extend(data[pos:pos + cs])
        pos += cs; br += cs

    if not compressed:
        return bytes(raw), pos

    # LZMA1 decompress
    lzma_header = bytes(raw[:5]) + b"\xff" * 8
    result = lzma.decompress(lzma_header + bytes(raw[5:]), format=lzma.FORMAT_ALONE)
    return result, pos


def parse_file_entries(block1: bytes, entry_start: int) -> list[FileEntry]:
    """Parse file entries from decompressed header block 1."""
    FIXED_AFTER_DEST = 136  # bytes after dest content (strings + binary fields)
    LOCATION_OFFSET = 108   # offset of location field within fixed data
    LOCATION_DIVISOR = 256  # location values are multiplied by 256

    entries = []
    pos = entry_start

    while pos + 8 < len(block1):
        # Read source string
        src_len = struct.unpack_from("<I", block1, pos)[0]
        if src_len > 10000:
            break
        pos += 4 + src_len

        # Read destination string
        if pos + 4 > len(block1):
            break
        dest_len = struct.unpack_from("<I", block1, pos)[0]
        if dest_len > 10000 or dest_len % 2 != 0:
            break
        dest_content = block1[pos + 4:pos + 4 + dest_len]
        dest = dest_content.decode("utf-16-le", errors="replace")
        pos += 4 + dest_len

        # Location field
        if pos + FIXED_AFTER_DEST > len(block1):
            break

        location_raw = struct.unpack_from("<I", block1, pos + LOCATION_OFFSET)[0]
        location = location_raw // LOCATION_DIVISOR
        pos += FIXED_AFTER_DEST

        if dest:
            entries.append(FileEntry(destination=dest, location=location))

    return entries


def parse_data_entries(block2: bytes) -> list[DataEntry]:
    """Parse data entries from decompressed header block 2."""
    # Entry size for 6.7.0 = 89 bytes:
    # first_slice(4) + last_slice(4) + chunk_offset(8) + file_offset(8) +
    # file_size(8) + chunk_size(8) + checksum(32) + timestamp(8) +
    # version_ms(4) + version_ls(4) + flags(1)
    ENTRY_SIZE = 89
    count = len(block2) // ENTRY_SIZE
    entries = []

    for i in range(count):
        off = i * ENTRY_SIZE
        chunk_offset = struct.unpack_from("<Q", block2, off + 8)[0]
        file_offset = struct.unpack_from("<Q", block2, off + 16)[0]
        file_size = struct.unpack_from("<Q", block2, off + 24)[0]
        chunk_size = struct.unpack_from("<Q", block2, off + 32)[0]
        flags = block2[off + 88]
        chunk_compressed = bool(flags & 0x10)
        call_filter = bool(flags & 0x04)

        entries.append(DataEntry(
            chunk_offset=chunk_offset,
            file_offset=file_offset,
            file_size=file_size,
            chunk_size=chunk_size,
            chunk_compressed=chunk_compressed,
            call_instruction_filter=call_filter,
        ))

    return entries


def decompress_chunk(data: bytes, data_offset: int, entry: DataEntry) -> bytes:
    """Decompress a file chunk from the data section."""
    pos = data_offset + entry.chunk_offset
    magic = data[pos:pos + 4]
    if magic != ZLB_MAGIC:
        raise RuntimeError(f"Expected zlb magic at {pos}, got {magic.hex()}")

    if not entry.chunk_compressed:
        return data[pos + 4:pos + entry.chunk_size]

    # LZMA1: zlb(4) + props(5) + stream (read to end, decoder handles EOS)
    props = data[pos + 4:pos + 9]
    lzma_header = props + b"\xff" * 8
    return lzma.decompress(lzma_header + data[pos + 9:], format=lzma.FORMAT_ALONE)


def resolve_path(path: str) -> str:
    """Strip Inno Setup variables from path."""
    path = path.replace("\\", "/")
    if path.lower().startswith("{app}/"):
        path = path[6:]
    elif path.lower().startswith("{app}"):
        path = path[5:]
    return path


def undo_call_instruction_filter(data: bytes) -> bytes:
    """Undo Inno Setup 5.3.9+ CALL/JMP instruction filter.

    Reverses the E8/E9 (CALL/JMP) relative-to-absolute address transform
    applied before compression. Handles both positive and negative ranges.
    """
    buf = bytearray(data)
    file_size = len(buf)
    i = 0
    while i < len(buf) - 5:
        if buf[i] in (0xE8, 0xE9):
            addr = struct.unpack_from("<I", buf, i + 1)[0]
            offset = i + 5
            if addr < file_size:
                new_addr = (addr - offset) & 0xFFFFFFFF
                struct.pack_into("<I", buf, i + 1, new_addr)
            elif addr >= (0x100000000 - offset):
                new_addr = (addr - file_size) & 0xFFFFFFFF
                struct.pack_into("<I", buf, i + 1, new_addr)
            i += 5
        else:
            i += 1
    return bytes(buf)


def find_file_entries_start(block1: bytes) -> int:
    """Find where file entries begin in the header block.
    
    File entries are sequential: each has source(str) + dest(str) + 136 fixed bytes.
    We find the start by locating two consecutive entries with {app}\\ destinations
    separated by exactly (136 + 4 + 0 + 4 + dest2_len) bytes.
    """
    app_utf16 = "{app}\\".encode("utf-16-le")

    # Collect all positions where {app}\ appears with valid entry pattern
    candidates = []
    pos = 0
    while pos < len(block1) - 20:
        pos = block1.find(app_utf16, pos)
        if pos == -1:
            break
        if pos >= 8:
            dest_len = struct.unpack_from("<I", block1, pos - 4)[0]
            src_len = struct.unpack_from("<I", block1, pos - 8)[0]
            if src_len == 0 and 10 < dest_len < 2000 and dest_len % 2 == 0:
                candidates.append((pos - 8, dest_len))
        pos += 1

    # Find first pair of consecutive candidates that match entry structure
    for i in range(len(candidates) - 1):
        entry1_start, dest1_len = candidates[i]
        entry2_start, dest2_len = candidates[i + 1]

        # Expected: entry1_start + 4(src) + 0 + 4(dest_len) + dest1_len + 136 == entry2_start
        expected_next = entry1_start + 4 + 0 + 4 + dest1_len + 136
        if expected_next == entry2_start:
            return entry1_start

    raise RuntimeError("Cannot find file entries start")


def extract(exe_path: Path, output_dir: Path):
    print(f"[*] Reading {exe_path}")
    data = exe_path.read_bytes()

    # 1. Find offsets
    header_offset, data_offset = find_offsets(data)
    version = data[header_offset:header_offset + 64].rstrip(b"\x00").decode("ascii")
    print(f"    {version}")
    print(f"    Header: {header_offset}, Data: {data_offset}")

    # 2. Decompress header blocks
    # After version(64) + encryption(53) = 117 bytes
    block1_offset = header_offset + 64 + 53
    print("[*] Decompressing header...")
    block1, block2_offset = decompress_block(data, block1_offset)
    block2, _ = decompress_block(data, block2_offset)
    print(f"    Block 1: {len(block1)} bytes, Block 2: {len(block2)} bytes")

    # 3. Parse file entries
    print("[*] Parsing file entries...")
    entry_start = find_file_entries_start(block1)
    files = parse_file_entries(block1, entry_start)
    print(f"    {len(files)} files")

    # 4. Parse data entries
    data_entries = parse_data_entries(block2)
    print(f"    {len(data_entries)} data entries")

    # 5. Extract
    print(f"[*] Extracting to {output_dir}...")
    chunk_cache: dict[int, bytes] = {}
    extracted = 0
    errors = 0

    for fe in files:
        if fe.location >= len(data_entries):
            errors += 1
            continue

        de = data_entries[fe.location]
        if de.file_size == 0:
            continue

        dest = resolve_path(fe.destination)
        if not dest:
            continue

        out_path = output_dir / dest
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if de.chunk_offset not in chunk_cache:
                chunk_cache[de.chunk_offset] = decompress_chunk(data, data_offset, de)

            chunk = chunk_cache[de.chunk_offset]
            file_data = chunk[de.file_offset:de.file_offset + de.file_size]
            if de.call_instruction_filter:
                file_data = undo_call_instruction_filter(file_data)
            out_path.write_bytes(file_data)
            extracted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    [-] {dest}: {e}")

    print(f"\n[+] Done. {extracted} files extracted, {errors} errors.")


def main():
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./sdk/Example.exe")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("./sdk/output")
    out.mkdir(parents=True, exist_ok=True)
    extract(exe, out)


if __name__ == "__main__":
    main()
