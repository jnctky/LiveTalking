# -*- coding: utf-8 -*-
"""Parallel segmented downloader (16 threads) with resume + integrity check.

Downloads big wheels from Aliyun pytorch-wheels mirror into my_tools/_tmp/downloads/.
Usage: python my_tools/parallel_download.py
"""
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from paths import TMP_DIR

DEST = str(TMP_DIR / "downloads")
SEGMENTS = 16

TARGETS = [
    ("torch-2.5.1+cu121-cp311-cp311-win_amd64.whl",
     "https://mirrors.aliyun.com/pytorch-wheels/cu121/torch-2.5.1%2Bcu121-cp311-cp311-win_amd64.whl"),
    ("torchvision-0.20.1+cu121-cp311-cp311-win_amd64.whl",
     "https://mirrors.aliyun.com/pytorch-wheels/cu121/torchvision-0.20.1%2Bcu121-cp311-cp311-win_amd64.whl"),
]


def head_size(url):
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers["Content-Length"])


def fetch_range(url, start, end, path, idx):
    part = "%s.seg%02d" % (path, idx)
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have >= end - start + 1:
        return
    req = urllib.request.Request(url)
    req.add_header("Range", "bytes=%d-%d" % (start + have, end))
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=120) as resp, open(part, "ab") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def download(name, url):
    path = os.path.join(DEST, name)
    if os.path.exists(path):
        print("SKIP(exists) %s" % name, flush=True)
        return
    total = head_size(url)
    print("%s total=%.0f MB  seg=%d" % (name, total / 1048576, SEGMENTS), flush=True)
    bounds = []
    seg = total // SEGMENTS
    for i in range(SEGMENTS):
        s = i * seg
        e = total - 1 if i == SEGMENTS - 1 else (i + 1) * seg - 1
        bounds.append((s, e))
    t0 = time.time()
    last = [0]
    with ThreadPoolExecutor(SEGMENTS) as ex:
        futures = {ex.submit(fetch_range, url, s, e, path, i): (s, e) for i, (s, e) in enumerate(bounds)}
        while True:
            done, fail = 0, 0
            for f in list(futures):
                if f.done():
                    try:
                        f.result()
                        done += 1
                    except Exception as exc:
                        fail += 1
                        print("seg retry: %r" % exc, flush=True)
                        s, e = futures[f]
                        futures[f] = ex.submit(fetch_range, url, s, e, path, list(futures).index(f))
            got = sum(os.path.getsize(p) for p in
                      (path + ".seg%02d" % i for i in range(SEGMENTS)) if os.path.exists(p))
            if got - last[0] >= 50 * 1048576 or (done + fail) == SEGMENTS:
                print("  %d/%d seg done, %.0f MB, %.1f MB/s" % (done, SEGMENTS, got / 1048576, got / max(time.time() - t0, 1) / 1048576), flush=True)
                last[0] = got
            if fail == 0 and done == SEGMENTS:
                break
            if fail > 0 and all(f.done() for f in futures):
                # reset failed segs by clearing their futures map entries
                nf = {}
                for i, f in enumerate(futures):
                    s, e = futures[f]
                    if f.done() and f.exception() is not None:
                        nf[ex.submit(fetch_range, url, s, e, path, i)] = (s, e)
                    else:
                        nf[f] = (s, e)
                futures.clear()
                futures.update(nf)
    # merge
    with open(path, "wb") as out:
        for i in range(SEGMENTS):
            with open(path + ".seg%02d" % i, "rb") as f:
                while True:
                    c = f.read(1024 * 1024)
                    if not c:
                        break
                    out.write(c)
    final = os.path.getsize(path)
    for i in range(SEGMENTS):
        os.remove(path + ".seg%02d" % i)
    ok = "OK" if final == total else "SIZE_MISMATCH(%d != %d)" % (final, total)
    print("DONE %s  %.0f MB  %.0fs  %s" % (name, final / 1048576, time.time() - t0, ok), flush=True)


os.makedirs(DEST, exist_ok=True)
for n, u in TARGETS:
    download(n, u)
print("ALL_DONE", flush=True)
