###############################################################################
#  WebRTC 连接管理 + RTC 音频/视频接收
###############################################################################

import json
import asyncio
import random
import copy
import time
from typing import Dict, Optional
import queue

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration
from aiortc.rtcrtpsender import RTCRtpSender

from utils.logger import logger


# def _rand_session_id(n: int = 6) -> int:
#     """生成 N 位随机 session ID"""
#     return random.randint(10 ** (n - 1), 10 ** n - 1)


from server.session_manager import session_manager
from server.session_manager import MaxSessionError

class RTCManager:
    """
    WebRTC 连接管理器。
    
    管理 PeerConnection 生命周期、音视频轨道收发、DataChannel。
    """

    def __init__(self, opt):
        """
        Args:
            opt: 全局配置
        """
        self.opt = opt
        self.pcs: set = set()
        # pc -> sessionid，用于按会话回收连接
        self._pc_sessions: Dict[object, str] = {}
        # pc -> 首次观察到链路不可用的时刻
        self._dead_since: Dict[object, float] = {}
        # 链路进入 disconnected 后允许的恢复杂宽限（秒）
        self._reap_grace = 20.0
        # 从未建立过连接的孤儿会话宽限（秒）
        self._orphan_grace = 60.0
        self._reaper_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    #  连接/会话回收
    # ------------------------------------------------------------------ #
    def _track(self, pc, sessionid):
        self.pcs.add(pc)
        self._pc_sessions[pc] = sessionid

    def _untrack(self, pc):
        self.pcs.discard(pc)
        self._pc_sessions.pop(pc, None)
        self._dead_since.pop(pc, None)

    @staticmethod
    def _is_dead(pc) -> bool:
        """链路是否已经不可能再传输媒体"""
        dead = ("failed", "closed", "disconnected")
        return pc.connectionState in dead or pc.iceConnectionState in dead

    async def _close_pc(self, pc):
        self._untrack(pc)
        try:
            await pc.close()
        except Exception:
            logger.exception("closing peer connection failed")

    async def release_session(self, sessionid: str) -> bool:
        """关闭该会话的所有 PeerConnection 并释放会话槽位。"""
        if not sessionid:
            return False
        existed = session_manager.has_session(sessionid) or any(
            sid == sessionid for sid in self._pc_sessions.values()
        )
        for pc, sid in list(self._pc_sessions.items()):
            if sid == sessionid:
                await self._close_pc(pc)
        session_manager.remove_session(sessionid)
        return existed

    async def _release_pc(self, pc, sessionid: Optional[str] = None):
        """回收单个连接，并在没有其它连接引用同一会话时释放会话。"""
        sid = sessionid or self._pc_sessions.get(pc)
        await self._close_pc(pc)
        if not sid:
            return
        if any(s == sid for s in self._pc_sessions.values()):
            return  # 该会话还有别的连接在用
        session_manager.remove_session(sid)

    async def _drop_if_dead(self, pc, sessionid: Optional[str] = None):
        if pc not in self.pcs:
            return
        if self._is_dead(pc):
            logger.info(
                "Releasing stale connection (connection=%s, ice=%s, session=%s)",
                pc.connectionState, pc.iceConnectionState, sessionid,
            )
            await self._release_pc(pc, sessionid)

    def start_reaper(self):
        """在当前事件循环中启动后台回收任务（需在 loop 运行前调用）。"""
        if self._reaper_task is None or self._reaper_task.done():
            loop = asyncio.get_event_loop()
            self._reaper_task = loop.create_task(self._reap_loop())

    async def _reap_loop(self, interval: float = 15.0):
        while True:
            await asyncio.sleep(interval)
            try:
                await self._reap_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("session reaper error")

    async def _reap_once(self):
        now = time.time()
        for pc in list(self.pcs):
            if self._is_dead(pc):
                since = self._dead_since.setdefault(pc, now)
                if now - since >= self._reap_grace:
                    logger.info(
                        "Reaping stale connection (connection=%s, ice=%s, session=%s)",
                        pc.connectionState, pc.iceConnectionState,
                        self._pc_sessions.get(pc),
                    )
                    await self._release_pc(pc)
            else:
                self._dead_since.pop(pc, None)

        # 从未建立连接的孤儿会话（客户端取消 / offer 后立即刷新）
        in_use = set(self._pc_sessions.values())
        for sid in session_manager.session_ids():
            if sid in in_use:
                continue
            if session_manager.age(sid) >= self._orphan_grace:
                logger.info("Reaping orphan session %s", sid)
                session_manager.remove_session(sid)

    async def _evict_one_stale(self) -> bool:
        """槽位已满时尝试挤掉一个肯定不再活动的会话。"""
        in_use = set(self._pc_sessions.values())
        for sid in session_manager.session_ids():
            pcs = [pc for pc, s in self._pc_sessions.items() if s == sid]
            if sid not in in_use or all(self._is_dead(pc) for pc in pcs):
                logger.info("Evicting stale session %s to free a slot", sid)
                await self.release_session(sid)
                return True
        return False

    async def _create_pc_and_answer(self, avatar_session, sessionid, offer):
        """创建 PeerConnection、添加轨道、SDP 交换，返回已完成 answer 的 pc"""
        # stun 为空时传空列表（禁用 STUN），否则传入指定 STUN
        ice_servers = [RTCIceServer(urls=self.opt.stun)] if self.opt.stun else []
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=ice_servers)
        )
        self._track(pc, sessionid)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = pc.connectionState
            logger.info("Connection state is %s", state)
            if state in ("failed", "closed"):
                await self._release_pc(pc, sessionid)
            elif state == "disconnected":
                # 浏览器刷新/断网常停在 disconnected；给一个宽限期后仍不可用才回收
                self._dead_since.setdefault(pc, time.time())
                asyncio.get_event_loop().call_later(
                    self._reap_grace,
                    lambda: asyncio.ensure_future(self._drop_if_dead(pc, sessionid)),
                )
            else:
                self._dead_since.pop(pc, None)

        # 添加发送轨道
        from server.webrtc import HumanPlayer
        player = HumanPlayer(avatar_session)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        # 设置编解码器偏好
        capabilities = RTCRtpSender.getCapabilities("video")
        preferences = list(filter(lambda x: x.name == "H264", capabilities.codecs))
        preferences += list(filter(lambda x: x.name == "VP8", capabilities.codecs))
        preferences += list(filter(lambda x: x.name == "rtx", capabilities.codecs))
        transceiver = pc.getTransceivers()[1]
        transceiver.setCodecPreferences(preferences)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return pc

    async def handle_offer(self, request):
        """处理 WebRTC offer 信令"""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        # 浏览器可传入稳定的 sessionid（刷新时相同）——直接复用同一槽位，
        # 否则每次刷新都会新建会话，旧连接滞留几个就顶满上限。
        client_sid = params.pop("sessionid", None) or None

        if client_sid and (session_manager.has_session(client_sid)
                           or any(s == client_sid for s in self._pc_sessions.values())):
            logger.info("Replacing existing session %s on reconnect", client_sid)
            await self.release_session(client_sid)

        try:
            sessionid = await session_manager.create_session(params, sessionid=client_sid)
        except MaxSessionError as e:
            # 先尝试挤掉确认已死的会话，再拒绝
            if await self._evict_one_stale():
                sessionid = await session_manager.create_session(params, sessionid=client_sid)
            else:
                logger.warning("Rejecting offer: %s", e)
                return web.Response(
                    content_type="application/json",
                    text=json.dumps({"code": -1, "msg": str(e)}),
                )
        logger.info('offer sessionid=%s', sessionid)

        pc = await self._create_pc_and_answer(
            session_manager.get_session(sessionid), sessionid, offer
        )

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
                "sessionid": sessionid,
            }),
        )

    async def handle_whep(self, request):
        """
        处理 WHEP 信令（WebRTC HTTP Egress Protocol）

        - 请求 body 为裸 SDP offer（Content-Type: application/sdp）
        - 扩展参数通过 query string 传入（avatar, tts, tts_server 等）
        - 返回 SDP answer（Content-Type: application/sdp）
        - sessionid 通过 X-Session-ID 响应头返回
        """
        params = dict(request.query)
        # 客户端可通过 query param 自定义 sessionid，不传则自动生成
        client_sid = params.pop("sessionid", None)

        offer_sdp = await request.text()
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")

        if client_sid and (session_manager.has_session(client_sid)
                           or any(s == client_sid for s in self._pc_sessions.values())):
            await self.release_session(client_sid)

        try:
            sessionid = await session_manager.create_session(params, sessionid=client_sid)
        except MaxSessionError as e:
            if await self._evict_one_stale():
                sessionid = await session_manager.create_session(params, sessionid=client_sid)
            else:
                logger.warning("Rejecting whep: %s", e)
                return web.Response(
                    status=503,
                    content_type="text/plain",
                    text=str(e),
                )
        logger.info("whep sessionid=%s", sessionid)

        pc = await self._create_pc_and_answer(
            session_manager.get_session(sessionid), sessionid, offer
        )

        return web.Response(
            status=201,
            content_type="application/sdp",
            text=pc.localDescription.sdp,
            headers={"X-Session-ID": sessionid},
        )

    async def handle_rtcpush(self, push_url, sessionid: str):
        """RTCPush 模式：主动推流"""
        import aiohttp
        await session_manager.create_session({}, sessionid)
        avatar_session = session_manager.get_session(sessionid)

        pc = RTCPeerConnection()
        self._track(pc, sessionid)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self._release_pc(pc, sessionid)

        from server.webrtc import HumanPlayer
        player = HumanPlayer(avatar_session)
        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        await pc.setLocalDescription(await pc.createOffer())

        async with aiohttp.ClientSession() as session:
            async with session.post(push_url, data=pc.localDescription.sdp) as response:
                answer_sdp = await response.text()

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type='answer')
        )

    async def shutdown(self):
        """关闭所有 PeerConnection"""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            self._reaper_task = None
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros, return_exceptions=True)
        self.pcs.clear()
        self._pc_sessions.clear()
        self._dead_since.clear()
