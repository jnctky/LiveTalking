"""LiveTalking WebRTC 端到端冒烟验证：
握手 -> 接收音视频轨 -> 抓几帧视频存 PNG -> 打印统计。

用法（项目根执行）:
    .venv/Scripts/python.exe my_tools/webrtc_smoke.py [--url http://127.0.0.1:8010] [--frames 5]
输出:
    my_tools/image/_smoke_frame_<n>.png
"""
import argparse
import asyncio
import json
import os
import sys
import time

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(*a):
    print(*a, flush=True)


async def run(url: str, want_frames: int):
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")

    got = {"video": 0, "audio": 0}
    done = asyncio.Event()

    @pc.on("track")
    def on_track(track):
        kind = track.kind
        log("收到轨:", kind)

        async def consume():
            while True:
                try:
                    if kind == "video":
                        frame: VideoFrame = await track.recv()
                        got["video"] += 1
                        if got["video"] <= want_frames:
                            out = os.path.join(ROOT, "my_tools", "image", "_smoke_frame_%d.png" % got["video"])
                            frame.to_image().save(out)
                            log("  帧%d %dx%d -> %s" % (got["video"], frame.width, frame.height, os.path.basename(out)))
                        if got["video"] >= want_frames and got["audio"] >= 1:
                            done.set()
                    else:
                        await track.recv()
                        got["audio"] += 1
                        if got["video"] >= want_frames and got["audio"] >= 1:
                            done.set()
                except Exception as e:
                    log("轨结束/异常(%s): %s" % (kind, type(e).__name__))
                    return

        asyncio.ensure_future(consume())

    pc.addTransceiver  # noqa
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    log("本地 SDP 就绪，POST /offer ...")

    async with aiohttp.ClientSession() as http:
        async with http.post(url.rstrip("/") + "/offer", json={
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
        }) as resp:
            data = await resp.json()
    log("answer sessionid =", data.get("sessionid"))
    if "sdp" not in data:
        log("握手失败:", data)
        return 1

    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
    log("远端 SDP 已设置，等待媒体 ...")

    try:
        await asyncio.wait_for(done.wait(), timeout=25)
    except asyncio.TimeoutError:
        log("等待超时（video=%d audio=%d）" % (got["video"], got["audio"]))

    await asyncio.sleep(0.5)
    await pc.close()
    log("统计: video=%d audio=%d" % (got["video"], got["audio"]))
    return 0 if got["video"] > 0 else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--frames", type=int, default=5)
    a = ap.parse_args()
    code = asyncio.run(run(a.url, a.frames))
    sys.exit(code)
