###############################################################################
#  全局会话管理器 (Session Manager)
###############################################################################

import asyncio
import time
import uuid
from typing import Dict, List, Optional
from utils.logger import logger
from avatars.base_avatar import BaseAvatar


class MaxSessionError(Exception):
    """会话数达到上限时抛出"""
    pass

def _rand_session_id() -> str:
    """生成 UUID session ID"""
    return str(uuid.uuid4())

class SessionManager:
    """
    全局数字人会话管理器。
    
    统一管理 avatar_sessions 生命周期，并在脱离 WebRTC 时依然保持服务可用。
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.sessions: Dict[str, BaseAvatar] = {}
            # sessionid -> 创建时刻，用于回收从未建立 WebRTC 连接的孤儿会话
            self.session_created_at: Dict[str, float] = {}
            self.build_session_fn = None
            self.max_session = 1   # default, override via set_max_session()
            self.initialized = True

    def set_max_session(self, n: int):
        """设置最大并发会话数"""
        self.max_session = max(1, n)

    def init_builder(self, build_session_fn):
        """配置用于构建 avatar_session 的工厂函数"""
        self.build_session_fn = build_session_fn
        
    def get_session(self, sessionid: str) -> Optional[BaseAvatar]:
        """获取已存活的会话"""
        return self.sessions.get(sessionid)

    def has_session(self, sessionid: str) -> bool:
        """检查会话是否存在"""
        return sessionid in self.sessions and self.sessions[sessionid] is not None

    def active_count(self) -> int:
        """当前占用槽位的会话数（含正在构建中的占位）"""
        return len(self.sessions)

    def session_ids(self) -> List[str]:
        """当前所有会话 id 的快照"""
        return list(self.sessions.keys())

    def age(self, sessionid: str) -> float:
        """会话存活秒数"""
        return time.time() - self.session_created_at.get(sessionid, 0.0)
        
    async def create_session(self, params: dict, sessionid: str = None) -> str:
        """
        在异步环境中创建一个新会话
        如果 sessionid 为 None，则自动生成。
        """
        if self.build_session_fn is None:
            raise Exception("SessionManager builder not initialized")
            
        if sessionid is None:
            sessionid = _rand_session_id()
            
        # 检查是否达到最大会话数（构建中的占位也计数，避免并发超卖）
        active_count = self.active_count()
        if active_count >= self.max_session:
            raise MaxSessionError(
                f"Maximum session limit reached ({active_count}/{self.max_session})"
            )

        logger.info('Creating sessionid=%s, current session num=%d', sessionid, active_count)
        # 预先占位防止重复
        self.sessions[sessionid] = None
        self.session_created_at[sessionid] = time.time()

        # 在线程池中构建 session（加载模型非常耗时）
        avatar_session = await asyncio.get_event_loop().run_in_executor(
            None, self.build_session_fn, sessionid, params
        )
        self.sessions[sessionid] = avatar_session
        return sessionid
        
    def add_session(self, sessionid: str, avatar_session: BaseAvatar):
        """同步添加静态或外部管理的会话（供非服务端入口调用）"""
        self.sessions[sessionid] = avatar_session
        self.session_created_at.setdefault(sessionid, time.time())
        
    def remove_session(self, sessionid: str):
        """销毁会话资源：置位 quit_event，级联停掉 render/推理/合帧/TTS 线程"""
        if sessionid in self.sessions:
            logger.info(f"Removing session {sessionid}")
            self.session_created_at.pop(sessionid, None)
            avatar_session = self.sessions.pop(sessionid, None)
            try:
                if avatar_session is not None and getattr(avatar_session, 'quit_event', None) is not None:
                    avatar_session.flush_talk()
                    avatar_session.quit_event.set()
            except Exception:
                logger.exception(f"session {sessionid} cleanup error")

# 单例抛出
session_manager = SessionManager()
