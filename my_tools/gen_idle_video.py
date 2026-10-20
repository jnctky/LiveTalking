# -*- coding: utf-8 -*-
"""
用本地 ComfyUI (MiniMax-H3 fl2va) 生成主持人 idle 动态视频。
- 底图: E:/work/airi-tachie/cutout/neutral.png (透明底抠图) 合成到深灰背景, 裁成 3:4
- first_frame == last_frame (同一张图) => 首尾无缝, 可循环
- 依赖用户已装好的 ComfyUI (D:/work/AI/ComfyUI) 与 MiniMax_H3 模型, 不下载任何新模型
用法: PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_idle_video.py [--resume]
"""
import argparse, json, sys, time, urllib.request, urllib.error
import cv2
import numpy as np

COMFY = "http://127.0.0.1:8188"
SRC = r"E:/work/airi-tachie/cutout/neutral.png"
COMFY_INPUT = r"D:/work/AI/ComfyUI/input"
OUT_DIR = r"D:/work/AI/ComfyUI/output/video"
MY = r"E:/work/LiveTalking/my_tools"
IMG_NAME = "presenter_idle_base.png"

W, H = 864, 1152          # 3:4 portrait
LENGTH = 124              # 17k+5 网格, ~5.17s @24fps
SEED = 20261018

# anim 版（原样保留）：只有呼吸/眨眼/极小幅头部动作
PROMPT_ANIM = (
    "integrated_multimodal_description: Photorealistic studio portrait video, static locked camera. "
    "[Shot 1] A professional young Chinese woman with black hair tied back, wearing a navy blue blazer "
    "and a white top, stands centered against a plain dark studio background. She faces the camera "
    "directly with a calm, gentle closed-lip smile. Throughout the shot she breathes naturally and "
    "gently, her chest and shoulders rising and falling subtly. She blinks naturally several times. "
    "Her head makes very small, slow, natural movements. Her hair, clothing and the background stay "
    "perfectly still. No speech, no talking, no hand gestures, no walking. Consistent face, consistent "
    "lighting, no camera movement, no zoom, no cuts."
)

# natural 版：眨眼 + 自然肢体动作（身体动作明显, 头部保持稳定以保住口型质量）
PROMPT_NATURAL = (
    "integrated_multimodal_description: Photorealistic studio portrait video, static locked camera. "
    "[Shot 1] A professional young Chinese woman with black hair tied back, wearing a navy blue blazer "
    "and a white top, stands centered against a plain dark studio background. She faces the camera "
    "with a calm, gentle closed-lip smile. Her head stays steady, centered and facing the camera, "
    "with only tiny natural micro-movements. Her upper body moves clearly and naturally: her "
    "shoulders and chest rise and fall with relaxed breathing, her torso sways gently from side to "
    "side as she shifts her weight between her feet, and her posture adjusts naturally with lively, "
    "alive energy. She blinks naturally several times. Her arms stay relaxed at her sides out of "
    "frame, her hands never enter the shot. Her mouth stays closed and smiling. Her hair and "
    "clothing follow her body motion naturally. No speech, no talking, no hand gestures in frame, "
    "no walking. Consistent face, consistent lighting, no camera movement, no zoom, no cuts."
)

PROMPTS = {"anim": PROMPT_ANIM, "natural": PROMPT_NATURAL}

# ---- 插入式微动作 (gesture clips) ----
# 设计要求: 同一角色/场景/光位; 起止都回到中性姿态(配合 first==last frame),
# 这样插回主循环时首尾帧与主循环基准姿态一致, 过渡只需很短 crossfade。
_BASE = (
    "integrated_multimodal_description: Photorealistic studio portrait video, static locked camera. "
    "[Shot 1] A professional young Chinese woman with black hair tied back, wearing a navy blue blazer "
    "and a white top, stands centered against a plain dark studio background. She faces the camera "
    "with a calm, gentle closed-lip smile. "
)
_TAIL = (
    " Her mouth stays closed, no speech, no talking. Her arms stay relaxed out of frame, her hands "
    "never enter the shot. Her hair and clothing follow her head and body motion naturally. "
    "Consistent face, consistent lighting, no camera movement, no zoom, no cuts."
)

# 点头: 两次缓慢自然的点头后回到静止中性
PROMPT_NOD = _BASE + (
    "She gives two slow, gentle, natural nods of her head while keeping eye contact with the camera, "
    "then returns to a still, neutral head position and holds it at the end of the shot. "
    "Her shoulders and chest rise and fall with relaxed breathing, and she blinks once naturally."
) + _TAIL

# 前倾强调: 上身微微前倾强调, 停一下, 再回正直立
PROMPT_LEAN = _BASE + (
    "She leans her upper body slightly forward toward the camera as if gently emphasizing a point, "
    "holds the lean briefly, then returns upright to her neutral standing posture and holds it at the "
    "end of the shot. Her head keeps facing the camera, her shoulders stay relaxed, and she breathes "
    "naturally."
) + _TAIL

PROMPTS.update({"nod": PROMPT_NOD, "lean": PROMPT_LEAN})

def prepare_image():
    img = cv2.imread(SRC, cv2.IMREAD_UNCHANGED)
    assert img is not None, f"读不到源图 {SRC}"
    if img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        rgb = img[:, :, :3].astype(np.float32)
        bg = np.full_like(rgb, 10.0)  # 近黑背景
        img = (rgb * a + bg * (1 - a)).astype(np.uint8)
    h, w = img.shape[:2]
    # 裁成 3:4 (0.75): 保宽裁高, 顶部留 36px 给头顶
    th = int(w / 0.75)
    if th <= h:
        top = min(36, h - th)
        img = img[top:top + th]
    else:
        tw = int(h * 0.75)
        left = (w - tw) // 2
        img = img[:, left:left + tw]
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    out = rf"{COMFY_INPUT}/{IMG_NAME}"
    cv2.imencode(".png", img)[1].tofile(out)
    print("底图就绪:", out, img.shape)

def build_graph():
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": r"MiniMax_H3\minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            "weight_dtype": "default"}},
        "2": {"class_type": "PathchSageAttentionKJ", "inputs": {
            "model": ["1", 0], "sage_attention": "auto", "allow_compile": False}},
        "3": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {"model": ["2", 0]}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["3", 0],
            "lora_name": r"minimax_h3\minimax_h3_turbo_4step_ema_ckpt850_pruned_comfyui.safetensors",
            "strength_model": 1.0}},
        "5": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["4", 0], "shift_video": 12.0, "shift_audio": 5.5}},
        "6": {"class_type": "BasicScheduler", "inputs": {
            "model": ["5", 0], "scheduler": "simple", "steps": 8, "denoise": 1.0}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": ARGS.seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["5", 0], "conditioning": ["20", 0]}},
        "20": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["11", 0], "vae": ["12", 0], "prompt": ARGS.prompt,
            "width": W, "height": H, "length": ARGS.length,
            "first_frame": ["13", 0], "last_frame": ["13", 0]}},
        "11": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": r"MiniMaxH3\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "type": "minimax", "device": "default"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "13": {"class_type": "LoadImage", "inputs": {"image": IMG_NAME}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["8", 0], "guider": ["9", 0], "sampler": ["7", 0],
            "sigmas": ["6", 0], "latent_image": ["20", 1]}},
        "21": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "22": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["21", 0], "frame_rate": 24, "loop_count": 0,
            "filename_prefix": "video/" + ARGS.out, "format": "video/h264-mp4",
            "pix_fmt": "yuv420p", "crf": 19, "save_metadata": True,
            "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }

def http_json(path, payload=None, timeout=30):
    url = COMFY + path
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--style", choices=sorted(PROMPTS), default="anim",
                    help="动效风格: anim=眨眼, natural=眨眼+肢体, nod=点头微动作, lean=前倾强调")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--length", type=int, default=LENGTH, help="帧数, 需满足 17k+5 网格")
    ap.add_argument("--out", default="idle_presenter", help="输出文件名前缀")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    args.prompt = PROMPTS[args.style]
    if (args.length - 5) % 17 != 0:
        raise SystemExit("length 需满足 17k+5 网格约束 (如 124=17*7+5, 158=17*9+5), 得到 %d" % args.length)
    ARGS = args
    print("style=%s seed=%d length=%d out=%s" % (args.style, args.seed, args.length, args.out))
    prepare_image()
    graph = build_graph()
    try:
        r = http_json("/prompt", {"prompt": graph, "client_id": "livetalking-idle"})
    except urllib.error.HTTPError as e:
        print("提交失败:", e.read().decode()[:2000]); sys.exit(1)
    pid = r["prompt_id"]
    print("已入队 prompt_id =", pid)
    t0 = time.time()
    while True:
        time.sleep(10)
        try:
            h = http_json(f"/history/{pid}", timeout=15)
        except Exception as e:
            print("poll err:", e); continue
        if pid not in h:
            print(f"[{int(time.time()-t0)}s] 排队/执行中 ..."); continue
        st = h[pid].get("status", {})
        if st.get("status_str") == "error":
            msgs = [m for m in st.get("messages", []) if m[0] == "execution_error"]
            print("执行出错:", json.dumps(msgs, ensure_ascii=False)[:3000]); sys.exit(2)
        if st.get("completed"):
            outs = h[pid]["outputs"]
            for nid, o in outs.items():
                for g in o.get("gifs", []) or o.get("videos", []) or []:
                    print("输出:", g.get("fullpath") or g.get("filename"))
            print(f"完成, 耗时 {int(time.time()-t0)}s"); return

if __name__ == "__main__":
    main()
