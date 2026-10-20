# -*- coding: utf-8 -*-
"""按 airi 的真实链路验证二期：逐句合成语音 → /humanaudio 上传(带情绪/句号/开关)。

airi 不是走 /human 文本接口，而是自己出 TTS 音频、按句上传到 /humanaudio。
本脚本模拟这条链路：edge-tts 逐句合成 → 16k 单声道 WAV → multipart 上传，
每句带 emotion / seg / semantic_emotion / sentence_split，然后在 WebRTC 上采帧，
最后从服务端日志里核对 clip_plan 的句边界与选段。

用法:
  PYTHONPATH=E:/work/LiveTalking .venv/Scripts/python.exe my_tools/humanaudio_probe.py \
      --avatar cafe_clips --semantic --sentence-split \
      --text "你好，很高兴见到你。今天想和你聊聊工作安排。请一定记住这个关键点。"

情绪按句自动推：warm / emphatic 交替由关键词决定（也可用 --emotions 显式指定）。
"""
import argparse
import asyncio
import io
import os
import sys

import aiohttp
import edge_tts
import numpy as np
import soundfile as sf
from aiortc import RTCPeerConnection, RTCSessionDescription

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from avatars import emotion as emo  # noqa: E402

LOG_PATH = os.path.join(ROOT, "my_tools", "log", "app_8010.log")


def log(*a):
    print(*a, flush=True)


def mp3_to_wav16k(data: bytes) -> bytes:
    """edge-tts 出的是 mp3, 解成 16k 单声道 PCM WAV(服务端 soundfile 直接可读)。"""
    import av
    from av.audio.resampler import AudioResampler

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        pcm = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pcm.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            pcm.append(out.to_ndarray().reshape(-1))
    samples = np.concatenate(pcm) if pcm else np.zeros(1600, dtype=np.int16)
    buf = io.BytesIO()
    sf.write(buf, samples, 16000, format="WAV", subtype="PCM_16")
    return buf.getvalue()


async def synth(text, voice):
    comm = edge_tts.Communicate(text, voice)
    chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


async def run(url, avatar, text, semantic, sentence, emotions, voice,
              sample_seconds):
    sentences = emo.split_sentences(text) if sentence else [text]
    log("句子 %d 段:" % len(sentences))
    for i, s in enumerate(sentences):
        e = ""
        if semantic:
            e = (emotions[i] if i < len(emotions) else emo.classify(s)) or "-"
        log("  [%d] %s  (emotion=%s)" % (i, s, e))

    pc = RTCPeerConnection()
    pc.addTransceiver("audio", direction="recvonly")
    pc.addTransceiver("video", direction="recvonly")
    frames = []

    @pc.on("track")
    def on_track(track):
        async def consume():
            while True:
                try:
                    if track.kind != "video":
                        await track.recv()
                        continue
                    frames.append(await track.recv())
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
    log("sessionid =", sid)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
    await asyncio.sleep(2.0)

    async with aiohttp.ClientSession() as http:
        for i, s in enumerate(sentences):
            mp3 = await synth(s, voice)
            wav = mp3_to_wav16k(mp3)
            form = aiohttp.FormData()
            form.add_field("sessionid", str(sid))
            form.add_field("file", wav, filename="speech.wav", content_type="audio/wav")
            form.add_field("seg", "probe-%d" % i)
            form.add_field("semantic_emotion", "1" if semantic else "0")
            form.add_field("sentence_split", "1" if sentence else "0")
            e = emotions[i] if i < len(emotions) else emo.classify(s)
            if semantic and e:
                form.add_field("emotion", e)
            async with http.post(url.rstrip("/") + "/humanaudio", data=form) as r:
                log("  upload[%d] -> %s %.2fs %s" % (i, r.status, len(wav) / 32000.0, await r.text()))

    log("采样 %.1fs ..." % sample_seconds)
    n0 = len(frames)
    await asyncio.sleep(sample_seconds)
    win = frames[n0:]
    log("采到 %d 帧" % len(win))

    # 口型量级(与 ab_test 同口径, 仅供参考, 结论仍看条带)
    if win:
        diffs = []
        prev = None
        for f in win:
            arr = np.asarray(f.to_image().convert("L"), dtype=np.float32)
            h, w = arr.shape
            m = arr[int(h * 0.45):int(h * 0.75), int(w * 0.3):int(w * 0.7)]
            if prev is not None:
                diffs.append(float(np.abs(m - prev).mean()))
            prev = m
        if diffs:
            log("嘴部帧差 mean=%.2f max=%.2f" % (np.mean(diffs), np.max(diffs)))
        for k, idx in enumerate(np.linspace(0, len(win) - 1, min(4, len(win))).astype(int)):
            win[idx].to_image().save(
                os.path.join(ROOT, "my_tools", "image", "_p2_%d.png" % k))

    try:
        async with aiohttp.ClientSession() as http:
            await http.post(url.rstrip("/") + "/session/close", json={"sessionid": sid})
    except Exception:
        pass
    await pc.close()

    # 服务端日志核对
    log("\n=== 服务端 clip_plan 日志 ===")
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-400:]
        for ln in lines:
            if "clip_plan" in ln:
                log("  " + ln.rstrip())
    except FileNotFoundError:
        log("  (找不到 %s)" % LOG_PATH)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--avatar", default=None)
    ap.add_argument("--text", default="你好，很高兴见到你。今天想和你聊聊工作安排。请一定记住这个关键点。")
    ap.add_argument("--semantic", action="store_true", help="按语义选情绪")
    ap.add_argument("--sentence-split", action="store_true", help="按句切音频")
    ap.add_argument("--emotions", default="", help="逐句情绪, 逗号分隔, 覆盖关键词推断")
    ap.add_argument("--voice", default="zh-CN-YunxiaNeural")
    ap.add_argument("--sample-seconds", type=float, default=14.0)
    a = ap.parse_args()
    emos = [x.strip() for x in a.emotions.split(",")] if a.emotions else []
    sys.exit(asyncio.get_event_loop().run_until_complete(
        run(a.url, a.avatar, a.text, a.semantic, a.sentence_split, emos,
            a.voice, a.sample_seconds)))
