# -*- coding: utf-8 -*-
"""把主循环 idle 与若干微动作片段合成为一条长序列（插入式微动作）。

思路: 主循环常驻, 说话到关键处插播 1-2 秒微动作, 播完回主循环。
插入片段的设计前提（gen_idle_video.py 的 nod/lean 提示词）:
  - 起止都回到中性姿态, 且 first_frame == last_frame
  - 因此 A 尾 / B 首 姿态相近, 7 帧 crossfade 就能无感衔接

重要: 过渡在"源帧层"完成。合成出来的是一条普通帧序列, 后续照常走 genavatar +
wav2lip, 口型仍然逐帧由音频驱动, 不受动作切换影响。

用法:
  PYTHONPATH= .venv/Scripts/python.exe my_tools/compose_gesture_idle.py \
      --idle my_tools/image/idle_natural_stab.mp4 \
      --insert my_tools/image/gesture_nod_stab.mp4 \
      --insert my_tools/image/gesture_lean_stab.mp4 \
      --rounds 3 --fade 7 --out my_tools/image/idle_with_gestures.mp4
"""
import argparse, os, sys

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def log(*a):
    print(*a, flush=True)


def read_frames(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("读不到视频: " + path)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        raise SystemExit("视频为空: " + path)
    return frames


def xfade_concat(a, b, fade):
    """A 尾与 B 头重叠 fade 帧做线性交叉, 总长 = len(a)+len(b)-fade。"""
    if fade <= 0:
        return a + b
    fade = min(fade, len(a), len(b))
    mixed = []
    for i in range(fade):
        alpha = (i + 1) / (fade + 1)          # 0→1, 从 A 渐变到 B
        mixed.append(cv2.addWeighted(a[len(a) - fade + i], 1 - alpha,
                                     b[i], alpha, 0))
    return a[:len(a) - fade] + mixed + b[fade:]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--idle", required=True, help="主循环视频")
    ap.add_argument("--insert", action="append", default=[],
                    help="插入的微动作视频, 可多次; 按顺序插在每轮 idle 之后")
    ap.add_argument("--rounds", type=int, default=3,
                    help="主循环轮数 (含首轮); 插入片段数不超过 rounds-1")
    ap.add_argument("--fade", type=int, default=7, help="交叉淡化帧数 (25fps 下 7 帧≈0.3s)")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    idle = read_frames(a.idle)
    inserts = [read_frames(p) for p in a.insert]
    log("主循环 %d 帧, 插入 %d 段: %s" % (len(idle), len(inserts), [len(x) for x in inserts]))
    if len(inserts) > max(0, a.rounds - 1):
        raise SystemExit("插入段数(%d) 超过 rounds-1(%d)" % (len(inserts), a.rounds - 1))

    h, w = idle[0].shape[:2]
    for i, seg in enumerate(inserts):
        if seg[0].shape[:2] != (h, w):
            raise SystemExit("第 %d 段尺寸 %s 与主循环 %s 不一致" % (i, seg[0].shape[:2], (h, w)))

    seq = list(idle)
    for r in range(1, a.rounds):
        if r - 1 < len(inserts):
            seg = inserts[r - 1]
            seq = xfade_concat(seq, seg, a.fade)      # idle → 微动作
            seq = xfade_concat(seq, idle, a.fade)     # 微动作 → idle
            log("第 %d 轮后插入 %d 帧, 当前总长 %d" % (r, len(seg), len(seq)))
        else:
            seq = xfade_concat(seq, idle, a.fade)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(a.out, fourcc, a.fps, (w, h))
    for f in seq:
        vw.write(f)
    vw.release()
    log("完成: %s  共 %d 帧 (%.1fs @%.0ffps)" % (a.out, len(seq), len(seq) / a.fps, a.fps))


if __name__ == "__main__":
    main()
