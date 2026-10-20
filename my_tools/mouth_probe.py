# -*- coding: utf-8 -*-
"""密集抓取说话中的帧, 拼嘴部特写条带, 检查口型是否错位/漂移。
用法: PYTHONPATH= .venv/Scripts/python.exe my_tools/mouth_probe.py --avatar lady_presenter_natural
"""
import argparse, glob, os, time
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
import aiohttp
import asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

async def run(avatar_id, out_prefix):
    session = aiohttp.ClientSession()
    sid = "mouthprobe-%d" % int(time.time())
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    frames = []

    @pc.on("track")
    def on_track(track):
        async def drain():
            while True:
                try:
                    f = await track.recv()
                except Exception:
                    return
                if track.kind == "video":
                    frames.append(f.to_ndarray(format="bgr24"))
        asyncio.ensure_future(drain())

    await pc.setLocalDescription(await pc.createOffer())
    body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid": sid, "avatar": avatar_id}
    async with session.post("http://127.0.0.1:8010/offer", json=body) as r:
        ans = await r.json()
        print("offer:", r.status, ans.get("code"), ans.get("msg"))
    await pc.setRemoteDescription(RTCSessionDescription(sdp=ans["sdp"], type=ans["type"]))
    print("webrtc connected, session:", sid)

    await asyncio.sleep(2.0)
    async with session.post("http://127.0.0.1:8010/human", json={
            "sessionid": sid, "text": "你好，欢迎来到直播间，今天我们聊聊数字人。", "type": "echo"},
            timeout=aiohttp.ClientTimeout(total=60)) as r:
        print("human:", r.status, await r.text())
    # 说话期间等帧
    n0 = len(frames)
    await asyncio.sleep(12.0)
    print("captured %d video frames during talk (had %d before)" % (len(frames) - n0, n0))

    await session.post("http://127.0.0.1:8010/session/close", json={"sessionid": sid})
    await pc.close()
    await session.close()

    fs = frames[n0:]
    if not fs:
        print("no frames!"); return
    h, w = fs[0].shape[:2]
    # 嘴部区域: 人脸大概在画面上部中央
    step = max(1, len(fs)//12)
    picks = list(range(0, len(fs), step))[:12]
    tiles = []
    for i in picks:
        f = fs[i]
        crop = f[int(h*0.26):int(h*0.46), int(w*0.28):int(w*0.72)]
        crop = cv2.resize(crop, (320, int(crop.shape[0]*320/crop.shape[1])))
        cv2.putText(crop, "#%d" % i, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        tiles.append(crop)
    rows = [np.hstack(tiles[i:i+3]) for i in range(0, len(tiles), 3)]
    grid = np.vstack(rows)
    out = os.path.join("my_tools", "image", "_mouthprobe_%s.png" % out_prefix)
    cv2.imwrite(out, grid)
    print("saved", out, grid.shape)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", default="lady_presenter_natural")
    ap.add_argument("--out", default="natural")
    a = ap.parse_args()
    asyncio.run(run(a.avatar, a.out))
