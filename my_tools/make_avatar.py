"""从图片 / 视频生成 LiveTalking-wav2lip 头像包。

⚠️ 已废弃，请改用官方脚本（本文件的裁剪逻辑会毁掉口型）:

    PYTHONPATH=. .venv/Scripts/python.exe avatars/wav2lip/genavatar.py \
        --video input.mp4 --avatar_id <id> --img_size 256

原因: 官方 genavatar 用 S3FD 竖长框（w/h≈0.7）直接裁剪，人脸占满画面；本文件
曾把框扩成正方形（+1.08 倍扩边），crop 变成头肩中景，嘴部有效像素过少，
表现为「嘴不张开 + 下巴变形」。详见 docs/avatar-pipeline.md 第五节。
保留本文件仅为历史参考，勿用于生成正式头像。

产物结构（与官方 wav2lip256_avatar1 一致）:
    data/avatars/<avatar_id>/full_imgs/00000000.png   # 完整帧
    data/avatars/<avatar_id>/face_imgs/00000000.png   # 256x256 人脸裁剪
    data/avatars/<avatar_id>/coords.pkl               # [(y1, y2, x1, x2), ...]

用法（在项目根执行）:
    .venv/Scripts/python.exe my_tools/make_avatar.py --image "E:/path/a.png" --avatar-id lady
    .venv/Scripts/python.exe my_tools/make_avatar.py --video "E:/path/idle.mp4" --avatar-id lady --fps 25
    .venv/Scripts/python.exe my_tools/make_avatar.py --video idle.mp4 --avatar-id lady --fps 25 --mouth-anchor 0.65

说明:
  - 带 alpha 的 PNG 会被合成到柔和灰底上（wav2lip 需要不透明帧）
  - 人脸检测用仓库自带 S3FD（权重需在 avatars/wav2lip/face_detection/detection/sfd/s3fd.pth）
  - 裁剪为正方形并向下留出下巴空间，输出 256x256（wav2lip256 的输入尺寸）
  - --mouth-anchor: 素材里人脸像素大小与官方差异大时必须加（如 0.65）。wav2lip 推理把
    256 crop 的下半部抹零重建，若 S3FD 框偏大导致嘴部落在 crop 上半部，口型会完全不动；
    该参数把嘴中心固定到 crop 的指定垂直比例（实测 0.65 ≈ 与官方 wav2lip256_avatar1 一致）
"""
import argparse
import os
import pickle
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


def log(*a):
    print(*a, flush=True)


def flatten_alpha(img_bgr, alpha):
    """把透明背景合成到柔和的竖直灰渐变底上。"""
    h, w = alpha.shape
    top = np.array([214, 214, 216], dtype=np.float32)     # BGR
    bottom = np.array([176, 178, 184], dtype=np.float32)
    ramp = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    bg = top[None, None, :] * (1 - ramp[:, :, None]) + bottom[None, None, :] * ramp[:, :, None]
    bg = np.repeat(bg, w, axis=1)
    a = (alpha.astype(np.float32) / 255.0)[:, :, None]
    out = img_bgr.astype(np.float32) * a + bg * (1 - a)
    return np.clip(out, 0, 255).astype(np.uint8)


def load_image(path):
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit("读不到图片: %s" % path)
    if raw.ndim == 3 and raw.shape[2] == 4:
        return flatten_alpha(raw[:, :, :3], raw[:, :, 3])
    if raw.ndim == 3:
        return raw
    return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)


def load_frames(path, fps=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return [load_image(path)]
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("读不到视频: %s" % path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    target = float(fps or src_fps)
    if target <= 0:
        raise SystemExit("--fps 必须为正数")
    # 按时间戳重采样：目标第 i 帧取源视频第 round(i * src_fps / target) 帧。
    # 这样 30fps -> 25fps 是真正丢帧而不是整段变慢（旧版用整数 step，1.2 会被取整成 1）。
    frames, idx, next_take = [], 0, 0
    ratio = src_fps / target
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx >= next_take:
            frames.append(frame)
            next_take = int(round(len(frames) * ratio))
        idx += 1
    cap.release()
    if not frames:
        raise SystemExit("视频里没取到帧: %s" % path)
    log("视频 %g fps -> 目标 %g fps: 读取 %d 帧, 保留 %d 帧 (%.2fs)"
        % (src_fps, target, idx, len(frames), len(frames) / target))
    return frames


def square_box(x1, y1, x2, y2, w, h, bottom_pad=0.18, side_scale=1.08, mouth_anchor=0.0):
    """把检测框扩成正方形（含下巴），并保证落在画面内。

    mouth_anchor > 0 时额外校准纵向构图: S3FD 框内嘴中心估计在框高 78% 处，
    调整框的 y 位置使嘴中心落在 crop 的 mouth_anchor 比例处。
    """
    y2 = y2 + (y2 - y1) * bottom_pad
    side = max(x2 - x1, y2 - y1) * side_scale
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    if mouth_anchor > 0:
        mouth_y = y1 + (y2 - y1 - (y2 - y1) * bottom_pad) * 0.78  # 框高 78% 处（不含 bottom_pad 扩展）
        cy = mouth_y - side * (mouth_anchor - 0.5)
    nx1, ny1 = cx - side / 2.0, cy - side / 2.0
    # 越界时先平移，平移不够再缩
    nx1 = min(max(nx1, 0), max(0, w - side))
    ny1 = min(max(ny1, 0), max(0, h - side))
    side = min(side, w, h)
    nx2, ny2 = nx1 + side, ny1 + side
    return int(round(nx1)), int(round(ny1)), int(round(nx2)), int(round(ny2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--video")
    ap.add_argument("--avatar-id", required=True)
    ap.add_argument("--out-dir", default="data/avatars")
    ap.add_argument("--size", type=int, default=256, help="face_imgs 边长，wav2lip256 用 256")
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--repeat", type=int, default=1, help="静态图重复帧数，1=单帧静止")
    ap.add_argument("--mouth-anchor", type=float, default=0.0,
                    help="嘴部构图校准: 嘴中心应落在 crop 的该垂直比例处 (如 0.64)。"
                         "wav2lip 推理时 crop 下半部被抹零重建，嘴若在分界线上方则口型不动；"
                         "S3FD 框大小随素材人脸像素大小变化，构图会失控，用此参数固定。0=不校准")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    if not args.image and not args.video:
        raise SystemExit("必须给 --image 或 --video")

    from avatars.wav2lip.face_detection.api import FaceAlignment, LandmarksType

    frames = load_frames(args.video or args.image, args.fps)
    if args.video is None and args.repeat > 1:
        frames = frames * args.repeat
    log("帧数:", len(frames), "首帧尺寸:", frames[0].shape[1], "x", frames[0].shape[0])

    fa = FaceAlignment(LandmarksType._2D, device=args.device)

    out = os.path.join(args.out_dir, args.avatar_id)
    full_dir = os.path.join(out, "full_imgs")
    face_dir = os.path.join(out, "face_imgs")
    os.makedirs(full_dir, exist_ok=True)
    os.makedirs(face_dir, exist_ok=True)

    coords = []
    last_box = None
    for i, frame in enumerate(frames):
        h, w = frame.shape[:2]
        det = fa.get_detections_for_batch(np.array([frame]))[0]
        if det is None:
            if last_box is None:
                raise SystemExit("第 %d 帧检测不到人脸，且没有可沿用的框" % i)
            log("  第 %d 帧未检出，沿用上一帧框" % i)
            box = last_box
        else:
            box = square_box(det[0], det[1], det[2], det[3], w, h, mouth_anchor=args.mouth_anchor)
        last_box = box
        x1, y1, x2, y2 = box
        face = frame[y1:y2, x1:x2]
        face = cv2.resize(face, (args.size, args.size), interpolation=cv2.INTER_LANCZOS4)
        cv2.imwrite(os.path.join(full_dir, "%08d.png" % i), frame)
        cv2.imwrite(os.path.join(face_dir, "%08d.png" % i), face)
        coords.append((y1, y2, x1, x2))
        if i < 3:
            log("  帧%d 人脸框 (x %d-%d, y %d-%d) 边长 %d" % (i, x1, x2, y1, y2, x2 - x1))

    with open(os.path.join(out, "coords.pkl"), "wb") as f:
        pickle.dump(coords, f)

    log("完成:", os.path.abspath(out))
    log("  full_imgs:", len(os.listdir(full_dir)), "face_imgs:", len(os.listdir(face_dir)),
        "coords:", len(coords))


if __name__ == "__main__":
    main()
