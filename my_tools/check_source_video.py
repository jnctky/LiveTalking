# -*- coding: utf-8 -*-
"""素材预检: 判断一个角色视频能否直接走官方 genavatar + wav2lip 管线。

检查四项（全部来自 S3FD 逐帧检测, 不依赖额外模型）:
  1. 基本信息     分辨率 / 帧数 / fps / 时长
  2. 检出稳定性   漏检帧数、脸框高度占画面比例（太小 -> crop 后嘴像素不足）
  3. 头部运动量   检测框逐帧一阶差分 95 分位（>10px 建议先稳定化, 否则直通）
  4. 嘴部开合度   嘴部暗区纵向跨度/脸高, 判断是否为「闭嘴待机」素材
                  （说话/咀嚼/抽烟素材不适合: 静默期会直接显示原帧, 会露馅）

用法:
    PYTHONPATH= .venv/Scripts/python.exe my_tools/check_source_video.py --video xxx.mp4
加 --plot 会输出开合度曲线与关键帧拼图到 my_tools/image/。
"""
import argparse
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

from paths import IMAGE_DIR, ensure  # noqa: E402


def log(*a):
    print(*a, flush=True)


def load_frames(path):
    cap = cv2.VideoCapture(path)
    frames, fps = [], cap.get(cv2.CAP_PROP_FPS) or 25.0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames, fps


def mouth_gap(frame, box):
    """嘴部最长连续暗块高度 / 脸高。闭嘴≈唇缝细线(接近0), 张嘴=口腔暗块显著。"""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    mx1, mx2 = int(x1 + 0.25 * w), int(x1 + 0.75 * w)
    my1, my2 = int(y1 + 0.58 * h), int(y1 + 0.92 * h)
    mx1, my1 = max(0, mx1), max(0, my1)
    roi = frame[my1:my2, mx1:mx2]
    if roi.size == 0:
        return 0.0
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    dark = (g < 70).sum(1)
    thr = max(3, int(0.10 * dark.shape[0] * 0.1) + 3)
    run = best = 0
    for v in dark:
        if v > thr:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return float(best / h)


def plot_curve(vals, path):
    """把开合度序列画成折线图（白线黑底, 带 0.5/p95 参考线）。"""
    W, H, pad = 900, 240, 24
    img = np.full((H, W, 3), 24, np.uint8)
    v = np.asarray(vals, dtype=np.float32)
    vmax = max(float(v.max()), 0.02)
    n = len(v)
    pts = []
    for i, x in enumerate(v):
        px = int(pad + i * (W - 2 * pad) / max(1, n - 1))
        py = int(H - pad - (x / vmax) * (H - 2 * pad))
        pts.append((px, py))
    cv2.polylines(img, [np.array(pts, np.int32)], False, (90, 220, 255), 1, cv2.LINE_AA)
    for lvl, color in ((np.percentile(v, 95), (120, 120, 120)), (0.5, (80, 80, 200))):
        py = int(H - pad - (lvl / vmax) * (H - 2 * pad))
        cv2.line(img, (pad, py), (W - pad, py), color, 1)
    cv2.putText(img, "mouth gap ratio (p95=%.3f max=%.3f)" % (np.percentile(v, 95), v.max()),
                (pad, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.imwrite(path, img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--plot", action="store_true", help="输出开合度曲线与关键帧拼图")
    args = ap.parse_args()

    ensure()
    from avatars.wav2lip.face_detection.api import FaceAlignment, LandmarksType
    fa = FaceAlignment(LandmarksType._2D, device="cuda")

    frames, fps = load_frames(args.video)
    if not frames:
        log("!! 读不到帧:", args.video)
        return 2
    H, W = frames[0].shape[:2]
    log("== 基本信息 ==")
    log("  %s" % os.path.basename(args.video))
    log("  %dx%d, %d 帧, %.2f fps, %.2f 秒" % (W, H, len(frames), fps, len(frames) / fps))

    dets = []
    for i in range(0, len(frames), args.batch):
        dets.extend(fa.get_detections_for_batch(np.array(frames[i:i + args.batch])))
    miss = [i for i, d in enumerate(dets) if d is None]
    log("== 检出 ==")
    log("  漏检 %d/%d 帧 %s" % (len(miss), len(dets), ("(帧 %s)" % miss[:10]) if miss else ""))
    for i, d in enumerate(dets):
        if d is None:  # 补洞: 沿用邻帧
            j, k = i - 1, i + 1
            while j >= 0 and dets[j] is None:
                j -= 1
            while k < len(dets) and dets[k] is None:
                k += 1
            dets[i] = dets[j] if j >= 0 else dets[k]
    if all(d is None for d in dets):
        log("!! 全程未检出人脸, 素材不可用")
        return 2

    a = np.array(dets, dtype=np.float64)
    cx, cy = (a[:, 0] + a[:, 2]) / 2, (a[:, 1] + a[:, 3]) / 2
    bw, bh = a[:, 2] - a[:, 0], a[:, 3] - a[:, 1]
    face_ratio = float(np.median(bh) / H)
    log("  脸高中位 %.0f px = 画面高 %.1f%%" % (np.median(bh), face_ratio * 100))

    d = np.abs(np.diff(np.stack([cx, cy, bh, bw], 1), axis=0))
    p95 = np.percentile(d, 95, axis=0)
    log("== 头部运动（逐帧一阶差分）==")
    log("  p95: 水平 %.1f px, 垂直 %.1f px, 脸高 %.1f px, 脸宽 %.1f px"
        % (p95[0], p95[1], p95[2], p95[3]))
    log("  全程位移: 水平 %.0f px, 垂直 %.0f px, 脸高变化 %.0f px"
        % (cx.max() - cx.min(), cy.max() - cy.min(), bh.max() - bh.min()))

    gaps = np.array([mouth_gap(f, d_) for f, d_ in zip(frames, dets)], dtype=np.float32)
    p95g, maxg, medg = np.percentile(gaps, 95), gaps.max(), np.median(gaps)
    # 张嘴帧: 开合度超过中位数 + 显著增量
    open_thr = medg + max(0.02, 0.6 * (p95g - medg))
    open_ratio = float((gaps > open_thr).mean())
    log("== 嘴部开合度 ==")
    log("  中位 %.3f, p95 %.3f, max %.3f, 明显张嘴帧占比 %.0f%%"
        % (medg, p95g, maxg, open_ratio * 100))

    log("== 结论 ==")
    verdict = []
    if len(miss) > len(dets) * 0.05:
        verdict.append("[x] 检出率偏低, 素材需重拍或调光")
    else:
        verdict.append("[v] 检出稳定")

    if face_ratio < 0.18:
        verdict.append("[!] 脸太小（<18%%画面高）, crop 后嘴像素不足, 口型会糊")
    elif face_ratio > 0.75:
        verdict.append("[!] 脸过大, 头部动作容易出框")
    else:
        verdict.append("[v] 脸占比合适")

    if p95[1] > 10 or p95[0] > 10:
        verdict.append("[!] 头动偏大（p95>10px）, 建议先 stabilize_head")
    else:
        verdict.append("[v] 头动温和, 可直通 genavatar（无需稳定化）")

    if open_ratio > 0.15 or p95g - medg > 0.06:
        verdict.append("[x] 素材里有明显说话/张嘴: 静默期会直接显示原帧, 会露馅 -> 需换闭嘴素材")
    else:
        verdict.append("[v] 嘴部基本闭合, 适合做待机素材")
    for v in verdict:
        log("  " + v)

    if args.plot:
        stem = os.path.splitext(os.path.basename(args.video))[0]
        cpath = IMAGE_DIR / ("_check_%s_curve.png" % stem)
        plot_curve(gaps, str(cpath))
        idx = np.linspace(0, len(frames) - 1, min(6, len(frames))).astype(int)
        tiles = []
        for i in idx:
            f = frames[i].copy()
            x1, y1, x2, y2 = [int(v) for v in dets[i]]
            cv2.rectangle(f, (x1, y1), (x2, y2), (0, 220, 255), 2)
            tiles.append(cv2.resize(f, (300, int(300 * H / W))))
        cv2.imwrite(str(IMAGE_DIR / ("_check_%s_frames.png" % stem)), cv2.hconcat(tiles))
        log("  曲线: %s" % cpath)
        log("  关键帧: %s" % (IMAGE_DIR / ("_check_%s_frames.png" % stem)))
    return 0 if not any(v.startswith("[x]") for v in verdict) else 1


if __name__ == "__main__":
    sys.exit(main())
