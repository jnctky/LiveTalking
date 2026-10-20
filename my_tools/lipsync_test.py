"""验证口型同步：握手 -> 发 TTS 文本（/human echo）-> 连续抓帧 -> 计算嘴部区域帧间差异。

用法（项目根执行）:
    .venv/Scripts/python.exe my_tools/lipsync_test.py --text "你好，我是你的数字人助手，今天天气真不错。"
输出:
    my_tools/image/_talk_<n>.png（说话期间抓帧）
    终端打印每帧与前一帧的差异（嘴部区域 vs 全图），差异明显抬升 = 口型在动
"""
import argparse
import asyncio
import os
import sys

import aiohttp
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def log(*a):
    print(*a, flush=True)


async def run(url: str, text: str, seconds: float, avatar: str = None):
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")

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
                    frame: VideoFrame = await track.recv()
                    frames.append(frame)
                    got_first.set()
                except Exception:
                    return

        asyncio.ensure_future(consume())

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    async with aiohttp.ClientSession() as http:
        offer_body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        if avatar:
            offer_body["avatar"] = avatar
        async with http.post(url.rstrip("/") + "/offer", json=offer_body) as resp:
            data = await resp.json()
    sid = data.get("sessionid")
    log("sessionid =", sid)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))

    await asyncio.wait_for(got_first.wait(), timeout=15)
    log("首帧到达，等 1.5s 取静默基线 ...")
    await asyncio.sleep(1.5)
    base_count = len(frames)

    log("发送 TTS 文本:", text)
    async with aiohttp.ClientSession() as http:
        async with http.post(url.rstrip("/") + "/human", json={
            "sessionid": sid, "type": "echo", "text": text}) as resp:
            log("/human ->", resp.status, await resp.text())

    t_end = asyncio.get_event_loop().time() + seconds
    sampled = []
    while asyncio.get_event_loop().time() < t_end:
        await asyncio.sleep(0.4)
        if len(frames) > sampled[-1] if sampled else False:
            pass
        sampled.append(len(frames))
    log("总帧数:", len(frames), "（说话窗口起始帧:", base_count, "）")

    # 取说话窗口的帧算差异
    win = frames[base_count:]
    diffs_mouth, diffs_all = [], []
    prev = None
    for f in win:
        arr = np.asarray(f.to_image().convert("RGB"), dtype=np.int16)
        h, w = arr.shape[:2]
        mouth = arr[int(h*0.36):int(h*0.46), int(w*0.42):int(w*0.58)]  # 人脸框中心的嘴部
        if prev is not None:
            diffs_mouth.append(float(np.abs(mouth - prev[0]).mean()))
            diffs_all.append(float(np.abs(arr - prev[1]).mean()))
        prev = (mouth, arr)
    if diffs_mouth:
        log("嘴部帧间差异: mean=%.2f max=%.2f" % (np.mean(diffs_mouth), np.max(diffs_mouth)))
        log("全图帧间差异: mean=%.2f max=%.2f" % (np.mean(diffs_all), np.max(diffs_all)))
    # 存 6 张抽样帧
    for i, idx in enumerate(np.linspace(0, len(win) - 1, min(6, len(win))).astype(int)):
        win[idx].to_image().save(os.path.join(ROOT, "my_tools", "image", "_talk_%d.png" % i))
    log("抽样帧已存 my_tools/image/_talk_*.png")

    await pc.close()
    ok = diffs_mouth and np.max(diffs_mouth) > 2.0
    log("结论:", "口型在动 ✅" if ok else "未见明显口型变化 ❌")
    return 0 if ok else 3


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--text", default="你好，我是你的数字人助手。今天想和你聊聊天，看看我的口型对不对。")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--avatar", default=None, help="指定头像 id（否则用服务端默认）")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.url, a.text, a.seconds, a.avatar)))
