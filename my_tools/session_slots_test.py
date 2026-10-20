"""会话槽位回归测试：验证浏览器反复刷新（同一 sessionid 重连）不会占满 max_session。

用法（项目根执行）:
    .venv/Scripts/python.exe my_tools/session_slots_test.py --rounds 8
"""
import argparse
import asyncio
import json
import os
import sys

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(*a):
    print(*a, flush=True)


async def one_offer(base: str, sessionid: str | None):
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
    if sessionid:
        body["sessionid"] = sessionid

    async with aiohttp.ClientSession() as http:
        async with http.post(f"{base}/offer", json=body) as resp:
            data = await resp.json()

    if data.get("code") == -1:
        await pc.close()
        return None, data.get("msg", "unknown")

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=data["sdp"], type=data["type"])
    )
    # 等一会儿，模拟真实观看一段
    await asyncio.sleep(1.5)
    await pc.close()
    return data.get("sessionid"), None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--sid", default="slot-test-stable")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    ok = 0
    for i in range(1, args.rounds + 1):
        sid, err = await one_offer(base, args.sid)
        if err:
            log(f"round {i}: REJECTED — {err}")
        else:
            ok += 1
            log(f"round {i}: ok (sessionid={sid})")
        await asyncio.sleep(0.5)

    log(f"\n结果: {ok}/{args.rounds} 成功（同一 sessionid 反复重连）")
    sys.exit(0 if ok == args.rounds else 1)


if __name__ == "__main__":
    asyncio.run(main())
