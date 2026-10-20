###############################################################################
#  服务器路由 — 统一异常处理的 API 路由
###############################################################################

import json
import os
import re
import uuid
import asyncio
from aiohttp import web

from avatars import emotion as emo
from utils.logger import logger


# ─── 二期开关与多片段元数据 ──────────────────────────────────────────────
# /human 与 /humanaudio 都可以携带这些字段, 由前端设置页的两个开关决定:
#   semantic_emotion: 按情绪挑对话动作片段
#   sentence_split:   按句切音频, 句边界换动作片段
# 缺省一律 False —— 老客户端不传时行为与一期完全一致。

def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def _feature_datainfo(src):
    """从请求参数(form 或 JSON)里取出情绪/句子/开关字段。

    seg 是句子标识: 同一句音频的所有帧共用一个 seg, 服务端据此判断句子边界。
    """
    out = {}
    if src.get("emotion"):
        out["emotion"] = str(src.get("emotion")).strip().lower()
    seg = src.get("seg")
    if seg not in (None, ""):
        out["seg"] = str(seg)
    for key in ("semantic_emotion", "sentence_split"):
        if key in src:
            out[key] = _as_bool(src.get(key), False)
    return out


def _with_segment(datainfo, index=None, text=None):
    """复制 datainfo 并补一个唯一 seg; 需要时按句文本补情绪。"""
    d = dict(datainfo)
    base = d.get("seg") or uuid.uuid4().hex[:8]
    d["seg"] = base if index is None else "%s-%d" % (base, index)
    if index is not None and d.get("semantic_emotion") and not d.get("emotion"):
        guessed = emo.classify(text)
        if guessed:
            d["emotion"] = guessed
    return d



# ─── 路由工具函数 ──────────────────────────────────────────────────────────

def json_ok(data=None):
    """返回成功 JSON 响应"""
    body = {"code": 0, "msg": "ok"}
    if data is not None:
        body["data"] = data
    return web.Response(
        content_type="application/json",
        text=json.dumps(body),
    )


def json_error(msg: str, code: int = -1):
    """返回错误 JSON 响应"""
    return web.Response(
        content_type="application/json",
        text=json.dumps({"code": code, "msg": str(msg)}),
    )


from server.session_manager import session_manager
from server.avatar_routes import setup_avatar_routes

def get_session(request, sessionid: str):
    """从 app 中获取 session 实例"""
    return session_manager.get_session(sessionid)


# ─── 路由处理函数 ──────────────────────────────────────────────────────────

async def human(request):
    """文本输入（echo/chat 模式），支持 voice/emotion 参数"""
    try:
        params: dict = await request.json()

        sessionid: str = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")

        if params.get('interrupt'):
            avatar_session.flush_talk()

        datainfo = {}
        if params.get('tts'):  # tts 参数透传（voice, emotion 等）
            datainfo['tts'] = params.get('tts')
        datainfo.update(_feature_datainfo(params))

        if params['type'] == 'echo':
            text = params['text']
            if datainfo.get('sentence_split'):
                # 一句一段音频: 每段带唯一 seg, 服务端在句边界换动作片段
                sents = emo.split_sentences(text)
                logger.info('human: 按句切分 %d 段 (semantic=%s)',
                            len(sents), datainfo.get('semantic_emotion'))
                for i, sent in enumerate(sents):
                    avatar_session.put_msg_txt(sent, _with_segment(datainfo, i, sent))
            else:
                avatar_session.put_msg_txt(text, _with_segment(datainfo))
        elif params['type'] == 'chat':
            llm_response = request.app.get("llm_response")
            if llm_response:
                asyncio.get_event_loop().run_in_executor(
                    None, llm_response, params['text'], avatar_session, datainfo
                )

        return json_ok()
    except Exception as e:
        logger.exception('human route exception:')
        return json_error(str(e))


async def interrupt_talk(request):
    """打断当前说话"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.flush_talk()
        return json_ok()
    except Exception as e:
        logger.exception('interrupt_talk exception:')
        return json_error(str(e))


async def humanaudio(request):
    """上传音频文件"""
    try:
        form = await request.post()
        sessionid = str(form.get('sessionid', ''))
        fileobj = form["file"]
        filebytes = fileobj.file.read()

        datainfo = _feature_datainfo(form)

        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.put_audio_file(filebytes, _with_segment(datainfo) if datainfo else {})
        return json_ok()
    except Exception as e:
        logger.exception('humanaudio exception:')
        return json_error(str(e))


async def set_audiotype(request):
    """设置自定义状态（动作编排）"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        avatar_session.set_custom_state(params['audiotype'])
        return json_ok()
    except Exception as e:
        logger.exception('set_audiotype exception:')
        return json_error(str(e))


async def record(request):
    """录制控制"""
    try:
        params = await request.json()
        sessionid = params.get('sessionid', '')
        avatar_session = get_session(request, sessionid)
        if avatar_session is None:
            return json_error("session not found")
        if params['type'] == 'start_record':
            avatar_session.start_recording()
        elif params['type'] == 'end_record':
            avatar_session.stop_recording()
        return json_ok()
    except Exception as e:
        logger.exception('record exception:')
        return json_error(str(e))


async def is_speaking(request):
    """查询是否正在说话"""
    params = await request.json()
    sessionid = params.get('sessionid', '')
    avatar_session = get_session(request, sessionid)
    if avatar_session is None:
        return json_error("session not found")
    return json_ok(data=avatar_session.is_speaking())

async def sse_handler(request):
    """SSE 事件流，推送服务器状态更新到客户端"""
    sessionid = request.query.get('sessionid', '')
    avatar_session = session_manager.get_session(sessionid)
    if avatar_session is None:
        return json_error("session not found")

    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        }
    )
    await response.prepare(request)

    import queue
    msgqueue = queue.Queue()
    avatar_session.add_msgqueue(msgqueue)

    try:
        while True:
            try:
                msg = msgqueue.get_nowait()
                await response.write(f"data: {msg}\n\n".encode('utf-8'))
            except queue.Empty:
                await asyncio.sleep(0.01)
    except (asyncio.CancelledError, ConnectionResetError):
        logger.info('SSE connection closed for session: %s', sessionid)
    finally:
        if msgqueue in avatar_session.msgqueues:
            avatar_session.msgqueues.remove(msgqueue)

    return response


async def admin_config(request):
    """Admin: 获取全局配置参数"""
    try:
        opt = request.app.get("opt")
        if opt:
            return json_ok(data={"config": vars(opt)})
        return json_error("Config not found")
    except Exception as e:
        logger.exception('admin_config exception:')
        return json_error(str(e))


AVATAR_ROOT = os.path.join("data", "avatars")
_AVATAR_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _avatar_dir(avatar_id: str):
    """把 avatar_id 解析成目录路径；非法 id 或目录不存在返回 None（防路径穿越）。"""
    if not avatar_id or not _AVATAR_ID_RE.match(avatar_id) or avatar_id in (".", ".."):
        return None
    path = os.path.join(AVATAR_ROOT, avatar_id)
    return path if os.path.isdir(path) else None


def _frame_names(avatar_dir: str):
    full = os.path.join(avatar_dir, "full_imgs")
    if not os.path.isdir(full):
        return []
    return sorted(
        n for n in os.listdir(full)
        if n.lower().endswith((".png", ".jpg", ".jpeg"))
    )


async def list_avatars(request):
    """列出可用头像，供前端下拉选择。

    切换方式：`POST /offer` 的 body 里带 `{"avatar": "<id>"}`，
    服务端会按需加载并缓存，无需重启进程或改 `--avatar_id`。
    """
    try:
        avatars = []
        if os.path.isdir(AVATAR_ROOT):
            for name in sorted(os.listdir(AVATAR_ROOT)):
                avatar_dir = _avatar_dir(name)
                if not avatar_dir:
                    continue
                frames = _frame_names(avatar_dir)
                if not frames:
                    continue  # 跳过不完整的目录（没有 full_imgs 帧）
                avatars.append({
                    "id": name,
                    "frames": len(frames),
                    "seconds": round(len(frames) / 25.0, 2),
                    "preview": f"/api/avatars/{name}/preview",
                })
        opt = request.app.get("opt")
        return json_ok(data={
            "avatars": avatars,
            "default": getattr(opt, "avatar_id", "") if opt else "",
        })
    except Exception as e:
        logger.exception('list_avatars exception:')
        return json_error(str(e))


async def avatar_preview(request):
    """返回头像首帧，用作选择器缩略图。"""
    avatar_dir = _avatar_dir(request.match_info.get("avatar_id", ""))
    if not avatar_dir:
        raise web.HTTPNotFound()
    frames = _frame_names(avatar_dir)
    if not frames:
        raise web.HTTPNotFound()
    return web.FileResponse(
        os.path.join(avatar_dir, "full_imgs", frames[0]),
        headers={"Cache-Control": "public, max-age=60"},
    )


async def admin_sessions(request):
    """Admin: 获取活跃的会话及其配置"""
    try:
        sessions_info = []
        for sid, avatar_session in session_manager.sessions.items():
            if avatar_session:
                s_opt = getattr(avatar_session, 'opt', None)
                s_data = {
                    "sessionid": sid,
                    "speaking": avatar_session.is_speaking() if hasattr(avatar_session, 'is_speaking') else False,
                    "recording": getattr(avatar_session, 'recording', False),
                }
                if s_opt:
                    s_data.update({
                        "model": getattr(s_opt, "model", ""),
                        "avatar_id": getattr(s_opt, "avatar_id", ""),
                        "REF_FILE": getattr(s_opt, "REF_FILE", ""),
                        "transport": getattr(s_opt, "transport", ""),
                        "batch_size": getattr(s_opt, "batch_size", 0),
                        "customopt": getattr(s_opt, "customopt", []),
                    })
                sessions_info.append(s_data)
        return json_ok(data={"sessions": sessions_info})
    except Exception as e:
        logger.exception('admin_sessions exception:')
        return json_error(str(e))


# ─── 路由注册 ──────────────────────────────────────────────────────────────

async def index(request):
    """默认首页重定向"""
    opt = request.app.get("opt")
    pagename = 'index.html'
    if opt and opt.transport == 'rtmp':
        pagename = 'rtmpapi.html'
    elif opt and opt.transport == 'rtcpush':
        pagename = 'rtcpushapi.html'
    raise web.HTTPFound(f'/{pagename}')


def setup_routes(app):
    """注册所有路由到 aiohttp app"""
    app.router.add_get("/", index)
    app.router.add_post("/human", human)
    app.router.add_post("/humanaudio", humanaudio)
    app.router.add_post("/set_audiotype", set_audiotype)
    app.router.add_post("/record", record)
    app.router.add_post("/interrupt_talk", interrupt_talk)
    app.router.add_post("/is_speaking", is_speaking)
    app.router.add_get("/api/admin/config", admin_config)
    app.router.add_get("/api/admin/sessions", admin_sessions)
    app.router.add_get("/api/avatars", list_avatars)
    app.router.add_get("/api/avatars/{avatar_id}/preview", avatar_preview)
    app.router.add_get('/sse', sse_handler)

    # ── Local ASR endpoint (SenseVoice/FunASR) ── Issue #604 ──
    try:
        from server.asr_server import asr_websocket_handler, is_funasr_available
        if is_funasr_available():
            app.router.add_get("/api/asr", asr_websocket_handler)
            logger.info("[ASR] Local SenseVoice ASR endpoint enabled at /api/asr")
        else:
            logger.info("[ASR] funasr not installed — local ASR endpoint disabled "
                        "(pip install funasr modelscope)")
    except Exception as e:
        logger.warning(f"[ASR] Failed to register ASR endpoint: {e}")

    # 注册 avatar 生成相关的路由
    setup_avatar_routes(app)

    app.router.add_static('/', path='web')
