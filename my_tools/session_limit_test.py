"""会话上限保护 + /session/close 释放验证。

步骤：
 1. 建立 max_session(5) 个并发连接占满槽位
 2. 第 6 个新 offer 应被拒（code=-1）
 3. 对其中一个调用 POST /session/close 释放
 4. 第 6 个应能成功接入
退出码 0 = 全部符合预期。
"""
import asyncio
import sys

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription

BASE = "http://127.0.0.1:8010"


async def offer(sid):
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    o = await pc.createOffer()
    await pc.setLocalDescription(o)
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{BASE}/offer", json={
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
            "sessionid": sid,
        }) as resp:
            data = await resp.json()
    if data.get("code") == -1:
        await pc.close()
        return None, data.get("msg")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
    return pc, None


async def close_session(sid):
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{BASE}/session/close", json={"sessionid": sid}) as resp:
            return resp.status


async def main():
    pcs = []
    for i in range(5):
        pc, err = await offer(f"limit-test-{i}")
        print(f"slot {i}: {'ok' if pc else 'REJECTED ' + str(err)}")
        if pc:
            pcs.append(pc)

    pc6, err6 = await offer("limit-test-overflow")
    print(f"第 6 个: {'ok' if pc6 else 'REJECTED — ' + str(err6)}")
    expect_reject = pc6 is None
    if pc6:
        pcs.append(pc6)

    status = await close_session("limit-test-0")
    print(f"/session/close limit-test-0 -> HTTP {status}")

    pc7, err7 = await offer("limit-test-after-close")
    print(f"释放后再接入: {'ok' if pc7 else 'REJECTED — ' + str(err7)}")

    for pc in pcs:
        await pc.close()
    if pc7:
        await pc7.close()
    for i in range(5):
        await close_session(f"limit-test-{i}")
    await close_session("limit-test-overflow")
    await close_session("limit-test-after-close")

    ok = expect_reject and pc7 is not None
    print("\n结果:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
