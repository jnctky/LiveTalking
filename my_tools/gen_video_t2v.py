# -*- coding: utf-8 -*-
"""纯文生视频（T2V）: 不需要底图, 完全由提示词驱动 MiniMax-H3 生成。

与 gen_idle_video.py 的区别:
  - gen_idle_video.py: 图生视频, 必须给底图, first==last 保证首尾无缝可循环
  - 本脚本: 不加载任何图片, MiniMaxH3ImageToVideo 的 first_frame/last_frame 都是
    optional, 不接即走纯文本条件; 角色长相完全由提示词+seed 决定

用途: 手上没有角色照片时快速出素材; 或 T2V 出满意的帧后截一帧当底图,
再转图生视频做多 clip(角色一致的动作组)。

注意: 纯 T2V 每次生成的角色不一致(seed 不同就是另一个人), 因此不能跨 clip
      复用同一角色; 需要多段动作组时请用 T2V 定角色 -> 截图当底图 -> I2V。

用法:
  PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_video_t2v.py \
      --prompt-file my_tools/prompt_cafe_presenter.txt --out cafe_t2v --length 124
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

COMFY = "http://127.0.0.1:8188"
UNET = r"MiniMax_H3\minimax_h3_fl2va_pruned_int8_convrot.safetensors"
LORA = r"minimax_h3\minimax_h3_turbo_4step_ema_ckpt850_pruned_comfyui.safetensors"
CLIP_NAME = r"MiniMaxH3\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE_NAME = "minimax_h3_video_vae_fp16.safetensors"


def log(*a):
    print(*a, flush=True)


def http_json(path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(COMFY + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def build_graph(a):
    """不含任何 LoadImage / first_frame / last_frame —— 纯文本条件。"""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "PathchSageAttentionKJ", "inputs": {
            "model": ["1", 0], "sage_attention": "auto", "allow_compile": False}},
        "3": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {"model": ["2", 0]}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["3", 0], "lora_name": LORA, "strength_model": 1.0}},
        "5": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["4", 0], "shift_video": a.shift_video, "shift_audio": a.shift_audio}},
        "6": {"class_type": "BasicScheduler", "inputs": {
            "model": ["5", 0], "scheduler": "simple", "steps": a.steps, "denoise": 1.0}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": a.seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["5", 0], "conditioning": ["20", 0]}},
        "20": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["11", 0], "vae": ["12", 0], "prompt": a.prompt,
            "width": a.width, "height": a.height, "length": a.length}},
        "11": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": CLIP_NAME, "type": "minimax", "device": "default"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["8", 0], "guider": ["9", 0], "sampler": ["7", 0],
            "sigmas": ["6", 0], "latent_image": ["20", 1]}},
        "21": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "22": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["21", 0], "frame_rate": a.fps, "loop_count": 0,
            "filename_prefix": "video/" + a.out, "format": "video/h264-mp4",
            "pix_fmt": "yuv420p", "crf": 19, "save_metadata": True,
            "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt-file", default=None, help="提示词文件（纯文本）")
    ap.add_argument("--prompt", default=None, help="直接给提示词（优先级高于 --prompt-file）")
    ap.add_argument("--width", type=int, default=864)
    ap.add_argument("--height", type=int, default=1152)
    ap.add_argument("--length", type=int, default=124, help="帧数, 需 17k+5 (124/158/243)")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--seed", type=int, default=20261020)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--shift-video", type=float, default=12.0)
    ap.add_argument("--shift-audio", type=float, default=5.5)
    ap.add_argument("--out", default="t2v_idle")
    a = ap.parse_args()

    if a.prompt:
        a.prompt = a.prompt.strip()
    elif a.prompt_file:
        with open(a.prompt_file, "r", encoding="utf-8") as f:
            a.prompt = f.read().strip()
    else:
        raise SystemExit("必须给 --prompt 或 --prompt-file")
    if not a.prompt:
        raise SystemExit("提示词为空")
    if (a.length - 5) % 17 != 0:
        raise SystemExit("length 需满足 17k+5 (如 124=17*7+5), 得到 %d" % a.length)

    log("T2V 模式（无底图）: %dx%d, %d 帧 @%dfps, seed=%d, steps=%d"
        % (a.width, a.height, a.length, a.fps, a.seed, a.steps))
    log("prompt (%d 字符): %s..." % (len(a.prompt), a.prompt[:100]))

    try:
        r = http_json("/prompt", {"prompt": build_graph(a), "client_id": "livetalking-t2v"})
    except urllib.error.HTTPError as e:
        log("提交失败:", e.read().decode()[:2000])
        return 1
    pid = r["prompt_id"]
    log("已入队 prompt_id =", pid)
    t0 = time.time()
    while True:
        time.sleep(10)
        try:
            h = http_json("/history/%s" % pid, timeout=15)
        except Exception as e:
            log("poll err:", e)
            continue
        if pid not in h:
            log("[%ds] 排队/执行中 ..." % int(time.time() - t0))
            continue
        st = h[pid].get("status", {})
        if st.get("status_str") == "error":
            msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
            log("执行出错:", json.dumps(msgs, ensure_ascii=False)[:3000])
            return 2
        if st.get("completed"):
            for nid, o in h[pid]["outputs"].items():
                for g in (o.get("gifs") or o.get("videos") or []):
                    log("输出:", g.get("fullpath") or g.get("filename"))
            log("完成, 耗时 %ds" % int(time.time() - t0))
            return 0


if __name__ == "__main__":
    sys.exit(main())
