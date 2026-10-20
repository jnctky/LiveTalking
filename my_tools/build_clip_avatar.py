# -*- coding: utf-8 -*-
"""拼接片段 → 多片段头像包（含 clips.json）。

流程:
1. 按 clips_v1.CLIPS 顺序读 my_tools/image/clips/<name>.mp4
2. 每段自动计算 exit 帧: 与起点帧(anchor)的差异曲线, 尾部连续低差异区起点
   (动作已回到中性、可安全切出的位置), 并夹到 [0.5L, L-3]
3. 硬拼成帧序列(所有片段首尾=anchor, 硬拼无感), 写 png → ffmpeg 编码
4. 调官方 genavatar 出 full_imgs/face_imgs/coords
5. 写 data/avatars/<id>/clips.json

用法: PYTHONPATH= .venv/Scripts/python.exe my_tools/build_clip_avatar.py \
        --avatar-id cafe_clips [--clips-dir my_tools/image/clips]
"""
import argparse
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clips_v1 import CLIPS  # noqa: E402
import paths  # noqa: E402

MY = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(MY)
PY = os.path.join(ROOT, ".venv/Scripts/python.exe")
ANCHOR = os.path.join(MY, "image", "clips", "_anchor.png")
FFMPEG = "ffmpeg"


def log(m):
    print(m, flush=True)


def exit_frame(frames, anchor, clip_type):
    """出口帧: 动作已回到中性、可安全切出的位置。

    idle: 动作幅度小、任意帧都接近中性 => 固定 60% 处, 压低说话切入延迟
    talk: 与起点帧的差异曲线, 尾部连续低差异区起点(动作演完的位置)
    """
    n = len(frames)
    if clip_type == "idle":
        log(f"    idle 片段: exit 取 60% -> {int(n * 0.6)}")
        return max(1, int(n * 0.6))
    diffs = [float(np.abs(f.astype(np.int16) - anchor.astype(np.int16)).mean())
             for f in frames]
    d = np.array(diffs)
    thr = max(3.0, float(d.min() + 0.25 * (d.max() - d.min())))
    tail = n - 1
    while tail > 0 and d[tail - 1] < thr:
        tail -= 1
    # tail = 尾部低差异区起点; 若整段都低(纯待机), tail≈0
    exit_idx = max(int(n * 0.5), min(tail, n - 3))
    log(f"    diff min/max={d.min():.1f}/{d.max():.1f} thr={thr:.1f} "
        f"tail_start={tail} exit={exit_idx}")
    return exit_idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar-id", default="cafe_clips")
    ap.add_argument("--clips-dir", default=os.path.join(MY, "image", "clips"))
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--skip-genavatar", action="store_true")
    args = ap.parse_args()

    anchor = cv2.imread(ANCHOR)
    assert anchor is not None, f"读不到起点帧 {ANCHOR}"

    plan, offset = [], 0
    segs = []
    for c in CLIPS:
        p = os.path.join(args.clips_dir, c["name"] + ".mp4")
        cap = cv2.VideoCapture(p)
        fr = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            fr.append(f)
        cap.release()
        assert fr, f"读不到片段 {p}"
        if fr[0].shape != anchor.shape:
            fr = [cv2.resize(f, (anchor.shape[1], anchor.shape[0])) for f in fr]
        log(f"  {c['name']}: {len(fr)} 帧")
        ex = exit_frame(fr, anchor, c["type"])
        plan.append({"name": c["name"], "type": c["type"],
                     "emotion": c.get("emotion", ""),
                     "start": offset, "end": offset + len(fr), "exit": offset + ex})
        segs.append(fr)
        offset += len(fr)

    total = offset
    log(f"拼接总帧数 {total} ({total/args.fps:.1f}s @ {args.fps}fps)")

    # 直接编码拼接视频
    tmp = os.path.join(paths.TMP_DIR, "clipconcat")
    shutil.rmtree(tmp, ignore_errors=True)
    paths.ensure()
    concat_mp4 = os.path.join(paths.TMP_DIR, "clipconcat.mp4")
    vw = cv2.VideoWriter(concat_mp4, cv2.VideoWriter_fourcc(*"mp4v"),
                         args.fps, (anchor.shape[1], anchor.shape[0]))
    i = 0
    for seg in segs:
        for f in seg:
            vw.write(f)
            i += 1
    vw.release()
    assert i == total

    avatar_dir = os.path.join(ROOT, "data", "avatars", args.avatar_id)
    if not args.skip_genavatar:
        env = os.environ.copy()
        env["PYTHONPATH"] = ROOT
        r = subprocess.run([PY, "-u", os.path.join(ROOT, "avatars/wav2lip/genavatar.py"),
                            "--video", concat_mp4, "--avatar_id", args.avatar_id,
                            "--img_size", "256"], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", cwd=ROOT)
        print((r.stdout or "")[-800:])
        assert r.returncode == 0, (r.stderr or "")[-2000:]

    import json
    meta = {"fps": args.fps, "forward_only": True, "clips": plan}
    with open(os.path.join(avatar_dir, "clips.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(f"clips.json 已写入 {avatar_dir}")
    for c in plan:
        log(f"  {c['name']:<12} {c['type']:<5} [{c['start']:>3},{c['end']:>3}) "
            f"exit={c['exit']} ({(c['end']-c['start'])/args.fps:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
