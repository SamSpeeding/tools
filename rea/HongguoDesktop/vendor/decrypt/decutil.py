"""Reconstructed from CPython 3.11 bytecode; this is not the original source.

The original ``decutil.pyc`` is retained separately for reference.  This module
implements the recovered functions directly and never loads that bytecode.
"""

import os
import re
import sys
import shutil
import subprocess

from Crypto.Cipher import AES
from Crypto.Util import Counter as CTRCounter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle


def _ff_exe(name):
    exe = name + (".exe" if os.name == "nt" else "")
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        for sub in (("tools", "ffmpeg", exe), ("ffmpeg", exe)):
            c = os.path.join(d, *sub)
            if os.path.isfile(c):
                return c
        d = os.path.dirname(d)
    return shutil.which(name)


def senc_iv8(ct_path):
    d = open(ct_path, "rb").read()
    ivs = []
    for m in re.finditer(b"senc", d):
        o = m.start() + 8 + 4
        if o + 8 > len(d):
            continue
        h = d[o:o + 8].hex()
        if h not in ivs:
            ivs.append(h)
    return ivs


def tenc_kid(ct_path):
    d = open(ct_path, "rb").read()
    m = re.search(b"tenc", d)
    if not m:
        return None
    o = m.start() + 8
    return d[o + 4:o + 20].hex() if o + 20 <= len(d) else None


def decrypt_full(ct_path, key_hex, base_iv64, out_path):
    K = bytes.fromhex(key_hex)
    biv = int(base_iv64, 16)
    data, sizes, offs = oracle.parse_video_samples(ct_path)
    data = bytearray(data)
    ok = 0
    for idx, (co, sz) in enumerate(zip(offs, sizes)):
        iv = (biv + idx) << 64
        pt = AES.new(
            K, AES.MODE_CTR, counter=CTRCounter.new(128, initial_value=iv)
        ).decrypt(bytes(data[co:co + sz]))
        if oracle._nal_ok(pt, sz):
            ok += 1
        data[co:co + sz] = pt
    open(out_path, "wb").write(data)
    print(f"  解密完成: {out_path}  (视频样本 NAL合法 {ok}/{len(sizes)})")
    return ok, len(sizes)


def _trak_senc_iv8(d, lo, hi):
    for m in re.finditer(b"senc", d):
        if lo <= m.start() < hi:
            o = m.start() + 8 + 4
            if o + 8 <= len(d):
                return d[o:o + 8].hex()
    return None


def _decrypt_track(buf, K, base_iv64, sizes, offs):
    biv = int(base_iv64, 16)
    for idx, (co, sz) in enumerate(zip(offs, sizes)):
        iv = (biv + idx) << 64
        buf[co:co + sz] = AES.new(
            K, AES.MODE_CTR, counter=CTRCounter.new(128, initial_value=iv)
        ).decrypt(bytes(buf[co:co + sz]))


def decrypt_av(ct_path, key_hex, out_path):
    d = open(ct_path, "rb").read()
    buf = bytearray(d)
    K = bytes.fromhex(key_hex)
    mv = oracle._find(d, [b"moov"])
    if not mv:
        raise RuntimeError("无 moov")
    stats = {}
    for t, o, sz, hs in oracle._ib(d, *mv):
        if t != b"trak":
            continue
        h = oracle._find(d, [b"mdia", b"hdlr"], o + hs, o + sz)
        handler = d[h[0] + 8:h[0] + 12] if h else None
        if handler not in (b"vide", b"soun"):
            continue
        iv8 = _trak_senc_iv8(d, o, o + sz)
        if not iv8:
            continue
        sizes, offs = oracle.parse_track_samples(d, handler)
        if not sizes:
            continue
        _decrypt_track(buf, K, iv8, sizes, offs)
        if handler == b"vide":
            ok = sum(
                1 for co, s in zip(offs, sizes)
                if oracle._nal_ok(bytes(buf[co:co + s]), s)
            )
            stats["vide"] = ok, len(sizes)
        else:
            stats["soun"] = None, len(sizes)
    open(out_path, "wb").write(buf)
    v = stats.get("vide")
    a = stats.get("soun")
    msg = []
    if v:
        msg.append(f"视频 NAL合法 {v[0]}/{v[1]}")
    if a:
        msg.append(f"音频 {a[1]} 样本")
    print(f"  全轨解密: {out_path}  ({'; '.join(msg)})")
    return stats


def strip_cenc(in_path, out_path):
    import struct as _s

    buf = bytearray(open(in_path, "rb").read())
    o = 0
    moov = None
    while o + 8 <= len(buf):
        sz = _s.unpack(">I", buf[o:o + 4])[0]
        typ = bytes(buf[o + 4:o + 8])
        if sz == 1:
            sz = _s.unpack(">Q", buf[o + 8:o + 16])[0]
        if sz < 8:
            break
        if typ == b"moov":
            moov = o + 8, o + sz
            break
        o += sz
    if not moov:
        return None
    CONTAINERS = {
        b"moov", b"minf", b"mvex", b"udta", b"edts", b"trak",
        b"mdia", b"stbl", b"gmhd", b"wave", b"dinf",
    }
    RENAME = {
        b"encv": b"hvc1", b"enca": b"mp4a", b"sinf": b"free",
        b"senc": b"free", b"saiz": b"free", b"saio": b"free",
    }
    n = [0]

    def kids(p, cstart, cend):
        if cstart + 8 <= cend:
            csz = _s.unpack(">I", buf[cstart:cstart + 4])[0]
            if 8 <= csz <= cend - cstart:
                walk(cstart, cend)
                return
        si = buf.find(b"sinf", p, cend)
        if si != -1:
            buf[si:si + 4] = b"free"
            n[0] += 1

    def walk(start, end):
        p = start
        while p + 8 <= end:
            sz = _s.unpack(">I", buf[p:p + 4])[0]
            typ = bytes(buf[p + 4:p + 8])
            hdr = 8
            if sz == 1:
                sz = _s.unpack(">Q", buf[p + 8:p + 16])[0]
                hdr = 16
            elif sz == 0:
                sz = end - p
            if sz < 8 or p + sz > end:
                break
            if typ in CONTAINERS:
                walk(p + hdr, p + sz)
            elif typ == b"stsd":
                walk(p + hdr + 8, p + sz)
            elif typ == b"encv":
                kids(p, p + hdr + 78, p + sz)
            elif typ == b"enca":
                kids(p, p + hdr + 28, p + sz)
            if typ in RENAME:
                buf[p + 4:p + 8] = RENAME[typ]
                n[0] += 1
            p += sz

    walk(*moov)
    if not n[0]:
        return None
    open(out_path, "wb").write(buf)
    return out_path


def remux_playable(in_path, out_path):
    ff = _ff_exe("ffmpeg")
    if ff:
        _flags = 134217728 if sys.platform.startswith("win") else 0
        r = subprocess.run(
            [ff, "-y", "-loglevel", "error", "-i", in_path,
             "-c", "copy", "-tag:v", "hvc1", out_path],
            capture_output=True, text=True, creationflags=_flags,
        )
        if r.returncode == 0 and os.path.exists(out_path):
            return out_path
        print(f"  [!] ffmpeg 重封装失败, 改用纯 Python 去 CENC: {r.stderr[:150]}")
    try:
        res = strip_cenc(in_path, out_path)
    except Exception as ex:
        print(f"  [!] strip_cenc 异常: {ex}")
        res = None
    if res:
        print("  [i] 已纯 Python 去 CENC(encv→hvc1/enca→mp4a), 视频+音频均可播")
    else:
        print("  [!] 去 CENC 失败(无 moov?), 文件残留 encv/enca 盒")
    return res
