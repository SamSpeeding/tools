"""Read ISO-BMFF indexes and decrypt requested byte ranges without a whole file.

Offsets and box sizes are preserved. Only encrypted sample bytes and CENC
metadata change, so the player can seek using the original sample tables.
"""
from bisect import bisect_right
from dataclasses import dataclass
import struct

from Crypto.Cipher import AES


class MediaFormatError(RuntimeError):
    pass


def require(condition, message='视频索引格式无效'):
    if not condition:
        raise MediaFormatError(message)


@dataclass(frozen=True)
class Box:
    kind: bytes
    start: int
    body: int
    end: int


def boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    while start < end:
        require(start + 8 <= end)
        size, kind = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            require(start + 16 <= end)
            size = struct.unpack_from('>Q', data, start + 8)[0]
            header = 16
        elif size == 0:
            size = end - start
        require(header <= size <= end - start)
        yield Box(kind, start, start + header, start + size)
        start += size


def child(data, parent, kind, optional=False):
    found = [b for b in boxes(data, parent.body, parent.end) if b.kind == kind]
    require(len(found) <= 1, '视频索引存在重复结构')
    if found:
        return found[0]
    require(optional, f'视频缺少 {kind.decode()} 索引')
    return None


def numbers(data, box, offset, count, code='I'):
    width = struct.calcsize('>' + code)
    require(0 <= count <= 1_000_000 and box.body + offset + count * width <= box.end)
    return struct.unpack_from('>' + str(count) + code, data, box.body + offset)


def sample_locations(data, stbl, total):
    stsz = child(data, stbl, b'stsz')
    fixed, count = numbers(data, stsz, 4, 2)
    require(0 < count <= 1_000_000)
    sizes = [fixed] * count if fixed else list(numbers(data, stsz, 12, count))
    stco = child(data, stbl, b'stco', True)
    if stco is None:
        stco = child(data, stbl, b'co64')
    chunks = numbers(data, stco, 8, numbers(data, stco, 4, 1)[0], 'Q' if stco.kind == b'co64' else 'I')
    stsc = child(data, stbl, b'stsc')
    run_count = numbers(data, stsc, 4, 1)[0]
    runs = numbers(data, stsc, 8, run_count * 3)
    runs = list(zip(runs[::3], runs[1::3], runs[2::3]))
    require(runs and runs[0][0] == 1 and chunks)
    require(all(1 <= first <= len(chunks) and per > 0 and desc == 1 for first, per, desc in runs),
            '暂不支持此视频的样本描述切换')
    require(all(a[0] < b[0] for a, b in zip(runs, runs[1:])))
    result, sample_index, run = [], 0, 0
    for index, offset in enumerate(chunks, 1):
        if run + 1 < len(runs) and index == runs[run + 1][0]:
            run += 1
        for _ in range(runs[run][1]):
            require(sample_index < count)
            size = sizes[sample_index]
            require(0 < size <= 16 * 1024 * 1024 and offset + size <= total,
                    '视频样本大小或位置无效')
            result.append((offset, size))
            offset += size
            sample_index += 1
    require(sample_index == count)
    return result


@dataclass(frozen=True)
class Span:
    start: int
    size: int
    iv: int
    encrypted_offset: int = 0


class MP4Stream:
    def __init__(self, read, total, key=None):
        self.read, self.total, self.key = read, total, key
        self.spans, self.video_samples = [], []
        self.moov_start, metadata = self._metadata()
        self.metadata = bytearray(metadata)
        root = next(boxes(metadata))
        require(root.kind == b'moov' and root.end == len(metadata))
        require(child(metadata, root, b'mvex', True) is None, '暂不支持分片 MP4 播放')
        for track in boxes(metadata, root.body, root.end):
            if track.kind != b'trak':
                continue
            mdia = child(metadata, track, b'mdia')
            hdlr = child(metadata, mdia, b'hdlr')
            require(hdlr.body + 12 <= hdlr.end)
            handler = metadata[hdlr.body + 8:hdlr.body + 12]
            if handler not in (b'vide', b'soun'):
                continue
            stbl = child(metadata, child(metadata, mdia, b'minf'), b'stbl')
            stsd = child(metadata, stbl, b'stsd')
            require(numbers(metadata, stsd, 4, 1)[0] == 1, '暂不支持多个编码描述')
            entries = list(boxes(metadata, stsd.body + 8, stsd.end))
            require(len(entries) == 1)
            entry = entries[0]
            if entry.kind not in (b'encv', b'enca'):
                continue
            require(key is not None and len(key) == 16, '视频缺少解密密钥')
            # VisualSampleEntry and version-zero AudioSampleEntry headers.
            skip = 78 if entry.kind == b'encv' else 28
            require(entry.body + skip <= entry.end)
            if entry.kind == b'enca':
                require(metadata[entry.body + 8:entry.body + 10] == b'\0\0', '暂不支持此音频描述版本')
            children = Box(entry.kind, entry.start, entry.body + skip, entry.end)
            sinf = child(metadata, children, b'sinf')
            frma = child(metadata, sinf, b'frma')
            require(frma.body + 4 == frma.end)
            codec = metadata[frma.body:frma.end]
            require(codec in (b'hvc1', b'hev1', b'avc1', b'mp4a'), '暂不支持此视频编码')
            schm = child(metadata, sinf, b'schm')
            require(metadata[schm.body + 4:schm.body + 8] == b'cenc', '暂不支持此视频加密方式')
            tenc = child(metadata, child(metadata, sinf, b'schi'), b'tenc')
            require(tenc.body + 24 <= tenc.end and metadata[tenc.body] == 0)
            require(metadata[tenc.body + 6] == 1)
            iv_size = metadata[tenc.body + 7]
            require(iv_size in (8, 16), '暂不支持此视频的 IV 长度')
            samples = sample_locations(metadata, stbl, total)
            senc = child(metadata, stbl, b'senc', True) or child(metadata, track, b'senc', True)
            require(senc is not None, '视频缺少逐样本加密信息')
            flags, count = numbers(metadata, senc, 0, 2)
            require(flags in (0, 2) and count == len(samples), '暂不支持此视频的加密样本布局')
            cursor = senc.body + 8
            for offset, size in samples:
                require(cursor + iv_size <= senc.end)
                iv = int.from_bytes(metadata[cursor:cursor + iv_size].ljust(16, b'\0'), 'big')
                cursor += iv_size
                if flags & 2:
                    require(cursor + 2 <= senc.end)
                    pairs = struct.unpack_from('>H', metadata, cursor)[0]
                    cursor += 2
                    require(cursor + 6 * pairs <= senc.end)
                    used = encrypted_offset = 0
                    for _ in range(pairs):
                        clear_size, cipher_size = struct.unpack_from('>HI', metadata, cursor)
                        cursor += 6
                        used += clear_size
                        require(used + cipher_size <= size)
                        if cipher_size:
                            self.spans.append(Span(offset + used, cipher_size, iv, encrypted_offset))
                        used += cipher_size
                        encrypted_offset += cipher_size
                    require(used == size, '子样本长度与视频样本不一致')
                else:
                    self.spans.append(Span(offset, size, iv))
            require(cursor == senc.end)
            if handler == b'vide':
                self.video_samples.extend(samples[:2])
            self.metadata[entry.start + 4:entry.start + 8] = codec
            self.metadata[sinf.start + 4:sinf.start + 8] = b'free'
            for box in [senc] + [b for b in boxes(metadata, stbl.body, stbl.end) if b.kind in (b'saio', b'saiz')]:
                self.metadata[box.start + 4:box.start + 8] = b'free'
        require(key is None or self.video_samples, '没有可验证的加密视频样本')
        self.spans.sort(key=lambda span: span.start)
        require(all(a.start + a.size <= b.start for a, b in zip(self.spans, self.spans[1:])),
                '加密样本范围重叠')
        self.offsets = [span.start for span in self.spans]

    def _metadata(self):
        offset = 0
        # Skip mdat by its declared size; a moov at EOF never requires a full download.
        for _ in range(256):
            require(offset + 8 <= self.total, '视频没有 moov 索引')
            header = self.read(offset, min(offset + 15, self.total - 1))
            size, kind = struct.unpack_from('>I4s', header)
            if size == 1:
                require(len(header) >= 16)
                size = struct.unpack_from('>Q', header, 8)[0]
                require(size >= 16)
            elif size == 0:
                size = self.total - offset
            require(8 <= size <= self.total - offset)
            require(kind != b'moof', '暂不支持分片 MP4 播放')
            if kind == b'moov':
                require(size <= 16 * 1024 * 1024, '视频索引过大')
                return offset, self.read(offset, offset + size - 1)
            offset += size
        raise MediaFormatError('视频顶层结构过多')

    def decrypt(self, start, data):
        output = bytearray(data)
        end = start + len(output)
        index = max(0, bisect_right(self.offsets, start) - 1)
        for index in range(index, len(self.spans)):
            span = self.spans[index]
            if span.start >= end:
                break
            first, last = max(start, span.start), min(end, span.start + span.size)
            if first >= last:
                continue
            skip = span.encrypted_offset + first - span.start
            cipher = AES.new(self.key, AES.MODE_CTR, nonce=b'', initial_value=span.iv + skip // 16)
            # Advance the keystream when a player's range starts inside an AES block.
            cipher.decrypt(bytes(skip % 16))
            output[first - start:last - start] = cipher.decrypt(bytes(output[first - start:last - start]))
        first, last = max(start, self.moov_start), min(end, self.moov_start + len(self.metadata))
        if first < last:
            output[first - start:last - start] = self.metadata[first - self.moov_start:last - self.moov_start]
        return bytes(output)

    def verify_key(self, nal_ok):
        for offset, size in self.video_samples:
            require(nal_ok(self.decrypt(offset, self.read(offset, offset + size - 1)), size),
                    '视频与解密参数不匹配，请重新播放')

    def read_range(self, start, end):
        require(0 <= start <= end < self.total)
        return self.decrypt(start, self.read(start, end))
