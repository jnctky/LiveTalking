# -*- coding: utf-8 -*-
"""头部稳定化: 把视频里每帧的人头对齐回基准位置, 身体动作原样保留。

背景: wav2lip 推理把 256 crop 下半部抹零重建、按逐帧 bbox 贴回。头部大幅移动时
bbox 跟着走 -> 贴回错位(下巴变形)、crop 内容姿态漂移(口型不重建)。把头稳定到
固定位置后 bbox 恒定, 上述两个问题一起消失, 身体动作不受影响。

方法: 每帧 S3FD 检测 -> 以首帧框为基准, 将头部区域(框外扩 pad)平移+缩放对齐
基准 -> 椭圆羽化贴回。输出无损 PNG 帧序列 (供 make_avatar --image 不可行, 直接
写帧目录再压缩成 mp4)。

用法: PYTHONPATH= .venv/Scripts/python.exe my_tools/stabilize_head.py \
        --video D:/work/AI/ComfyUI/output/video/idle_natural_a_00001.mp4 \
        --out D:/work/AI/ComfyUI/output/video/idle_natural_stab.mp4
"""
import argparse, os, sys
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


def log(*a):
    print(*a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pad", type=float, default=1.35, help="头部区域外扩系数(含头发)")
    ap.add_argument("--feather", type=float, default=0.22, help="羽化带占区域半径比例")
    ap.add_argument("--fps", type=float, default=25.0)
    args = ap.parse_args()

    from avatars.wav2lip.face_detection.api import FaceAlignment, LandmarksType
    fa = FaceAlignment(LandmarksType._2D, device="cuda")

    cap = cv2.VideoCapture(args.video)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    log("读取 %d 帧" % len(frames))
    H, W = frames[0].shape[:2]

    dets = []
    B = 8
    for i in range(0, len(frames), B):
        batch = np.array(frames[i:i+B])
        dets.extend(fa.get_detections_for_batch(batch))
    n_bad = sum(1 for d in dets if d is None)
    log("检测完成, 未检出 %d 帧 (沿用邻帧框)" % n_bad)
    # 补洞
    for i, d in enumerate(dets):
        if d is None:
            j = i - 1
            while j >= 0 and dets[j] is None:
                j -= 1
            k = i + 1
            while k < len(dets) and dets[k] is None:
                k += 1
            dets[i] = dets[j] if j >= 0 else dets[k]

    # 基准: 全程中位框 (比首帧更稳, 免得首帧恰好偏一点)
    arr = np.array([[ (d[0]+d[2])/2, (d[1]+d[3])/2, (d[3]-d[1]) ] for d in dets])
    cx0, cy0, h0 = np.median(arr[:, 0]), np.median(arr[:, 1]), np.median(arr[:, 2])
    side0 = max(arr[:, 2] - arr[:, 0]).max() if False else np.median(arr[:, 2] - arr[:, 0])
    side0 = max(side0, h0)
    log("基准框中心 (%.0f, %.0f) 边长中位 %.0f 最大偏移: cx %.0fpx cy %.0fpx side %.0fpx"
        % (cx0, cy0, side0, np.abs(arr[:, 0]-cx0).max(), np.abs(arr[:, 1]-cy0).max(),
           (arr[:, 2]-arr[:, 0]).max()))

    region = int(side0 * args.pad)
    half = region // 2
    region = half * 2  # 偶数
    # 羽化 mask (椭圆, 中心实心 -> 边缘渐隐)
    yy, xx = np.mgrid[0:region, 0:region]
    nx = (xx - region/2) / (region/2)
    ny = (yy - region/2) / (region/2)
    r = np.sqrt(nx**2 + ny**2)
    feather = args.feather
    alpha = np.clip((1.0 - r) / feather, 0, 1)[..., None].astype(np.float32)
    mask = (alpha * 255).astype(np.uint8)

    vw = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (W, H))
    moved = 0
    for i, (frame, d) in enumerate(zip(frames, dets)):
        x1, y1, x2, y2 = d
        cx, cy = (x1+x2)/2.0, (y1+y2)/2.0
        side = max(x2-x1, y2-y1)
        scale = side0 / side
        # 从当前帧取头部区域(以检测框为中心, region*scale 大小), 对齐缩放到基准
        src_half = half / scale
        sx1 = int(round(cx - src_half)); sy1 = int(round(cy - src_half))
        sx2 = int(round(cx + src_half)); sy2 = int(round(cy + src_half))
        # 越界钳制
        sx1c, sy1c = max(0, sx1), max(0, sy1)
        sx2c, sy2c = min(W, sx2), min(H, sy2)
        crop = frame[sy1c:sy2c, sx1c:sx2c]
        canvas = np.zeros((region, region, 3), np.uint8)
        if crop.size:
            ox, oy = sx1c - sx1, sy1c - sy1
            cw, ch = crop.shape[1], crop.shape[0]
            tx1, ty1 = int(round(ox*scale)), int(round(oy*scale))
            crop_rs = cv2.resize(crop, (int(round(cw*scale)), int(round(ch*scale))),
                                 interpolation=cv2.INTER_LANCZOS4)
            ch2 = min(crop_rs.shape[0], region); cw2 = min(crop_rs.shape[1], region)
            crop_rs = crop_rs[:ch2, :cw2]
            tx1 = min(max(tx1, 0), region-ch2); ty1 = min(max(ty1, 0), region-ch2)
            canvas[ty1:ty1+ch2, tx1:tx1+cw2] = crop_rs
        # 贴回基准位置
        px1, py1 = int(cx0 - region/2), int(cy0 - region/2)
        px1c, py1c = max(0, px1), max(0, py1)
        px2c, py2c = min(W, px1+region), min(H, py1+region)
        if px2c <= px1c or py2c <= py1c:
            vw.write(frame); continue
        sub = canvas[py1c-py1:py2c-py1, px1c-px1:px2c-px1].astype(np.float32)
        msub = mask[py1c-py1:py2c-py1, px1c-px1:px2c-px1].astype(np.float32) / 255.0
        base = frame[py1c:py2c, px1c:px2c].astype(np.float32)
        frame[py1c:py2c, px1c:px2c] = (sub * msub + base * (1 - msub)).astype(np.uint8)
        if abs(cx-cx0) > 1 or abs(cy-cy0) > 1 or abs(side-side0) > 1:
            moved += 1
        vw.write(frame)
    vw.release()
    log("完成: %s (头部实际移动的帧: %d/%d)" % (args.out, moved, len(frames)))


if __name__ == "__main__":
    main()
