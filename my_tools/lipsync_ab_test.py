# -*- coding: utf-8 -*-
"""口型驱动 A/B 对照测试: 同一会话先采静默、再采说话, 对比嘴部运动量。

背景: lipsync_test.py 只算说话窗口的嘴部帧差。对 idle 素材本身动作大的头像
(如 sample1 抽烟吐烟), 该值会被素材自带动淹没, 必须有静默基线做对照。

判定: speak_mouth 显著高于 silent_mouth (>1.5x 且差值>1.5) 才算驱动生效。

用法: PYTHONPATH= .venv/Scripts/python.exe my_tools/lipsync_ab_test.py \
        --avatar lady_presenter_sample1
输出截图: my_tools/image/_ab_silent_*.png / _ab_speak_*.png
"""
import argparse, asyncio, os, sys

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


def log(*a):
    print(*a, flush=True)


def mouth_diffs(frames, box=None):
    """嘴部帧间灰度差。box=(y0,y1,x0,x1) 绝对像素(来自头像 coords); 缺省退回比例窗口。"""
    diffs, prev = [], None
    for f in frames:
        arr = np.asarray(f.to_image().convert("RGB"), dtype=np.int16)
        h, w = arr.shape[:2]
        if box is not None:
            y0, y1, x0, x1 = box
        else:
            y0, y1, x0, x1 = int(h*0.40), int(h*0.56), int(w*0.38), int(w*0.60)
        m = arr[y0:y1, x0:x1]
        g = cv2_gray(m)
        if prev is not None:
            diffs.append(float(np.abs(g - prev).mean()))
        prev = g
    return diffs


def load_mouth_box(avatar):
    """从头像包 coords.pkl 取中位脸框, 推嘴部窗口 (y0,y1,x0,x1) 绝对像素。

    原因: 固定比例窗口只适合"脸居中占满"的旧素材; T2V 等新构图的窗口会落到
    衬衫上, 测出 ratio≈1.0 的假阴性。coords 是逐帧脸框, 中位数即稳态位置。"""
    p = os.path.join(ROOT, "data", "avatars", avatar, "coords.pkl")
    if not os.path.exists(p):
        log("!! 找不到 %s, 退回比例窗口" % p)
        return None
    import pickle
    a = np.array(pickle.load(open(p, "rb")), dtype=float)
    y1, y2 = float(np.median(a[:, 0])), float(np.median(a[:, 1]))
    x1, x2 = float(np.median(a[:, 2])), float(np.median(a[:, 3]))
    h, w = y2 - y1, x2 - x1
    box = (int(y1 + 0.52*h), int(y1 + 0.92*h), int(x1 + 0.22*w), int(x1 + 0.78*w))
    log("嘴部窗口(来自 coords): %s" % (box,))
    return box


def cv2_gray(arr):
    # BT.601 灰度
    return arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


async def run(url, avatar, text, silent_s, speak_s):
    pc = RTCPeerConnection()
    pc.addTransceiver("audio", direction="recvonly")
    pc.addTransceiver("video", direction="recvonly")

    frames = []
    got_first = asyncio.Event()

    @pc.on("track")
    def on_track(track):
        async def consume():
            while True:
                try:
                    if track.kind != "video":
                        await track.recv()
                        continue
                    frames.append(await track.recv())
                    got_first.set()
                except Exception:
                    return
        asyncio.ensure_future(consume())

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    if avatar:
        body["avatar"] = avatar
    async with aiohttp.ClientSession() as http:
        async with http.post(url.rstrip("/") + "/offer", json=body) as r:
            data = await r.json()
    sid = data.get("sessionid")
    log("sessionid =", sid, " avatar =", avatar or "(服务端默认)")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))

    await asyncio.wait_for(got_first.wait(), timeout=15)
    # 跳过前 1s(连接抖动), 静默采样
    await asyncio.sleep(1.0)
    n0 = len(frames)
    await asyncio.sleep(silent_s)
    n1 = len(frames)
    silent_win = frames[n0:n1]
    log(f"静默采样 {len(silent_win)} 帧")

    async with aiohttp.ClientSession() as http:
        async with http.post(url.rstrip("/") + "/human", json={
                "sessionid": sid, "type": "echo", "text": text}) as r:
            log("/human ->", r.status, await r.text())

    # 等 TTS 首音频就绪后开始采样说话窗口
    await asyncio.sleep(2.0)
    n2 = len(frames)
    await asyncio.sleep(speak_s)
    speak_win = frames[n2:n2 + int(speak_s * 25)]
    log(f"说话采样 {len(speak_win)} 帧")

    try:
        async with aiohttp.ClientSession() as http:
            await http.post(url.rstrip("/") + "/session/close",
                            json={"sessionid": sid})
    except Exception:
        pass
    await pc.close()

    mbox = load_mouth_box(avatar)
    sd = mouth_diffs(silent_win, mbox)
    sp = mouth_diffs(speak_win, mbox)
    out = {}
    if sd:
        out["silent"] = (float(np.mean(sd)), float(np.max(sd)))
    if sp:
        out["speak"] = (float(np.mean(sp)), float(np.max(sp)))
    log("嘴部帧间差异  静默: mean=%.2f max=%.2f" % out.get("silent", (0, 0)))
    log("嘴部帧间差异  说话: mean=%.2f max=%.2f" % out.get("speak", (0, 0)))
    if "silent" in out and "speak" in out:
        ratio = out["speak"][0] / max(out["silent"][0], 1e-6)
        delta = out["speak"][0] - out["silent"][0]
        ok = ratio > 1.5 and delta > 1.5
        log("驱动增量: ratio=%.2fx delta=%.2f -> %s" %
            (ratio, delta, "口型驱动生效 ✅" if ok else "未见驱动增量，需人工看帧 ❌"))
    # 存帧
    for tag, win in (("silent", silent_win), ("speak", speak_win)):
        for i, idx in enumerate(np.linspace(0, len(win) - 1, min(4, len(win))).astype(int)):
            win[idx].to_image().save(
                os.path.join(ROOT, "my_tools", "image", "_ab_%s_%d.png" % (tag, i)))
    # 嘴部密集条带: 每5帧抽1张嘴部crop横向拼接, 供目检口型开合节奏
    for tag, win in (("silent", silent_win), ("speak", speak_win)):
        tiles = []
        for f in win[::5]:
            arr = np.asarray(f.to_image().convert("RGB"))
            if mbox is not None:
                y0, y1, x0, x1 = mbox
                m = arr[y0:y1, x0:x1]
            else:
                h, w = arr.shape[:2]
                m = arr[int(h*0.38):int(h*0.62), int(w*0.34):int(w*0.66)]
            tiles.append(cv2_resize(m, (150, 120)))
        if tiles:
            strip = np.concatenate(tiles, axis=1)[:, :, ::-1]
            cv2_imwrite(os.path.join(ROOT, "my_tools", "image", "_ab_%s_strip.png" % tag), strip)
            log(f"{tag} 条带: {len(tiles)} 格 -> my_tools/image/_ab_{tag}_strip.png")
    log("抽样帧已存 my_tools/image/_ab_*.png")
    return 0


def cv2_resize(arr, size):
    import cv2
    return cv2.resize(arr, size)


def cv2_imwrite(path, arr):
    import cv2
    cv2.imwrite(path, arr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--avatar", default=None)
    ap.add_argument("--text", default="你好，我是你的数字人助手。今天想和你聊聊天，看看我的口型对不对。")
    ap.add_argument("--silent-seconds", type=float, default=4.0)
    ap.add_argument("--speak-seconds", type=float, default=10.0)
    a = ap.parse_args()
    sys.exit(asyncio.get_event_loop().run_until_complete(
        run(a.url, a.avatar, a.text, a.silent_seconds, a.speak_seconds)))
