# -*- coding: utf-8 -*-
"""批量生成多片段素材（一期）。

逐个调用 gen_idle_video.py（first==last frame = 起点帧），把产出规范化拷贝到
my_tools/image/clips/<name>.mp4，并对每段跑一次轻量检查（帧数/尺寸/首尾差）。

用法:
  PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_clip_set.py [--only name1,name2]
产物:
  my_tools/image/clips/<name>.mp4
  my_tools/log/_clipset.log
"""
import argparse
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clips_v1 import ANCHOR, BASE, CLIPS, TAIL  # noqa: E402
import paths  # noqa: E402

MY = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = r"D:/work/AI/ComfyUI/output/video"
CLIP_DIR = os.path.join(MY, "image", "clips")
PY = os.path.join(os.path.dirname(MY), ".venv/Scripts/python.exe")
SEED = 20261020
W, H = 768, 1024  # 3:4, 脸高约 190px（crop 到 256 放大 1.35x，口型质量与 864 版基本一致）


def log(msg):
    print(msg, flush=True)


def gen_one(c, width, height):
    name = c["name"]
    out = f"clip_{name}"
    img_name = f"clipbase_{name}.png"
    prompt_file = os.path.join(paths.TMP_DIR, f"_prompt_{name}.txt")
    paths.ensure()
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(c["motion"].join([BASE, TAIL]))

    cmd = [
        PY, "-u", os.path.join(MY, "gen_idle_video.py"),
        "--image", os.path.join(MY, "image", "clips", "_anchor.png"),
        "--img-name", img_name,
        "--prompt-file", prompt_file,
        "--width", str(width), "--height", str(height),
        "--length", str(c["length"]),
        "--seed", str(SEED),
        "--out", out,
    ]
    log(f"== 生成 {name} ({c['length']} 帧, {width}x{height}) ...")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = "\n".join((r.stdout or "").strip().splitlines()[-3:])
    if r.returncode != 0:
        log(f"  失败 rc={r.returncode}\n{tail}\n{(r.stderr or '')[-600:]}")
        return None
    src = os.path.join(OUT_DIR, out + "_00001.mp4")
    if not os.path.exists(src):
        # VHS 有时序号偏移, 找最新
        cands = sorted([f for f in os.listdir(OUT_DIR) if f.startswith(out)],
                       key=lambda f: os.path.getmtime(os.path.join(OUT_DIR, f)))
        if not cands:
            log(f"  找不到输出 {out}: {tail}")
            return None
        src = os.path.join(OUT_DIR, cands[-1])
    dst = os.path.join(CLIP_DIR, f"{name}.mp4")
    shutil.copyfile(src, dst)
    log(f"  完成 -> {dst}")
    return dst


def check(dst, want_len):
    c = cv2.VideoCapture(dst)
    fr = []
    while True:
        ok, f = c.read()
        if not ok:
            break
        fr.append(f)
    c.release()
    if not fr:
        return None
    d01 = float(np.abs(fr[0].astype(int) - fr[-1].astype(int)).mean())
    return dict(frames=len(fr), size=fr[0].shape[1::-1], loop_diff=round(d01, 2),
                len_ok=(len(fr) == want_len))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只生成指定片段, 逗号分隔")
    ap.add_argument("--width", type=int, default=W)
    ap.add_argument("--height", type=int, default=H)
    args = ap.parse_args()

    os.makedirs(CLIP_DIR, exist_ok=True)
    todo = [c for c in CLIPS if not args.only or c["name"] in args.only.split(",")]
    log(f"共 {len(todo)} 段: {[c['name'] for c in todo]}")
    results = {}
    for c in todo:
        dst = gen_one(c, args.width, args.height)
        if dst:
            st = check(dst, c["length"])
            results[c["name"]] = st
            log(f"  检查: {st}")
    log("=== 汇总 ===")
    for k, v in results.items():
        log(f"  {k}: {v}")
    bad = [k for k, v in results.items() if not v or not v["len_ok"]]
    log("异常片段: " + (",".join(bad) if bad else "无"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
