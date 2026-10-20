"""验证 LiveTalking 按请求切换头像：GET /api/avatars + /offer 带 avatar 字段。

用法（项目根，服务已启动）：
    PYTHONPATH= .venv/Scripts/python.exe my_tools/avatars_api_test.py
"""

import asyncio
import json

import aiohttp
from aiortc import RTCPeerConnection

BASE = "http://127.0.0.1:8010"


async def offer_with_avatar(session: aiohttp.ClientSession, avatar_id: str, sid: str) -> dict:
    pc = RTCPeerConnection()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    await pc.setLocalDescription(await pc.createOffer())
    body = {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
        "sessionid": sid,
    }
    if avatar_id:
        body["avatar"] = avatar_id
    async with session.post(f"{BASE}/offer", json=body) as resp:
        data = await resp.json()
        data["_http_status"] = resp.status
    await pc.close()
    return data


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE}/api/avatars") as resp:
            payload = await resp.json()
        avatars = payload["data"]["avatars"]
        print("可用头像:")
        for a in avatars:
            print(f"  - {a['id']:<24} {a['frames']:>4} 帧  {a['seconds']}s")
        print("服务端默认:", payload["data"]["default"])

        for idx, avatar in enumerate(avatars):
            sid = f"avatar-switch-test-{idx}"
            result = await offer_with_avatar(session, avatar["id"], sid)
            ok = result.get("code", 0) == 0 and "sdp" in result
            print(f"\n[{'PASS' if ok else 'FAIL'}] offer avatar={avatar['id']} "
                  f"http={result['_http_status']} session={result.get('sessionid')}")

            async with session.get(f"{BASE}/api/admin/sessions") as resp:
                sessions = (await resp.json())["data"]["sessions"]
            mine = next((s for s in sessions if s["sessionid"] == sid), {})
            print(f"       服务端会话 avatar_id = {mine.get('avatar_id')}")

            async with session.post(f"{BASE}/session/close",
                                    json={"sessionid": sid}) as resp:
                await resp.json()

        # 清理：确认会话已释放
        async with session.get(f"{BASE}/api/admin/sessions") as resp:
            remaining = (await resp.json())["data"]["sessions"]
        left = [s for s in remaining if str(s["sessionid"]).startswith("avatar-switch-test-")]
        print(f"\n残留测试会话: {len(left)} 个")


if __name__ == "__main__":
    asyncio.run(main())
