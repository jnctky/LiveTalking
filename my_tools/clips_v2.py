# -*- coding: utf-8 -*-
"""二期扩充片段定义（v2）：大幅手部动作 + 长情绪片段。

与 clips_v1 的差别：
- idle 片段动作幅度更大，明确以手部动作为主（挥手/撩发/整袖口），
  每段 124 帧（≈5.2s @24fps），给待机轮播更多变化
- talk 片段改为 447 帧长片段（≈18.6s @24fps），覆盖 10s 以上的整段回答，
  减少多段拼接。长片段设计成「两段手势乐句」：前半段一组手势 -> 中段回到
  中性姿态停顿（= 出口帧位置，exit_frac≈0.5）-> 后半段另一组手势 -> 结尾
  回到起点帧。这样：
    * 句切模式: 新句子要等出口帧才切段，整段回答基本由一条长 clip 覆盖
    * 回待机: speech 结束最多等 ~9s（中段停顿）就能切出，不会无声比划到片尾
- 所有片段仍然 first==last==anchor（起点帧），跨片段硬切无感
- 嘴全程闭合、手不碰脸（wav2lip 按音频重绘整脸，情绪只能靠身体表达）

length 网格: 17k+5。124=17*7+5，447=17*26+5。
"""

from clips_v1 import BASE, TAIL, CLIPS as _V1_CLIPS, ANCHOR

SEED = 20261020

# type: idle=待机轮播 / talk=说话期动作（emotion 用于二期语义选择）
# exit_frac: 显式出口帧比例（覆盖 build_clip_avatar 的自动尾检测）；
#            仅长 talk 片段需要（中段回中性停顿处），idle/短 talk 走自动。
CLIPS_V2 = [
    # ---------- 待机：大幅手部动作 ----------
    {
        "name": "idle_wave",
        "type": "idle",
        "emotion": "",
        "length": 124,
        "motion": (
            "Motion: She greets the viewer with her hand: the hand resting on her lap "
            "rises to about shoulder height in a smooth, graceful arc, palm open toward "
            "the camera, and she waves gently two or three times from the wrist, with a "
            "warm closed-lip smile and a slight welcoming tilt of her head. She then "
            "lowers her hand smoothly back to her lap and settles into stillness."
        ),
    },
    {
        "name": "idle_hair",
        "type": "idle",
        "emotion": "",
        "length": 124,
        "motion": (
            "Motion: She raises her hand from the armrest, sweeps a loose strand of hair "
            "back from her shoulder in one fluid, elegant motion, the movement carrying "
            "through her forearm and wrist, then her hand glides back down to rest on the "
            "armrest. Her torso rotates very slightly with the gesture and settles back. "
            "Her head stays facing the camera and her hand stays at shoulder height or "
            "below, never touching her face."
        ),
    },
    {
        "name": "idle_cuff",
        "type": "idle",
        "emotion": "",
        "length": 124,
        "motion": (
            "Motion: She glances down briefly, uses her right hand to adjust the cuff of "
            "her left sleeve with a small, deliberate pinch-and-smooth motion, then "
            "releases, sits back up straight and returns her gaze to the camera with a "
            "soft closed-lip smile. Both hands settle back to their original resting "
            "places, one on the armrest and one on her lap."
        ),
    },
    # ---------- 长情绪片段（warm）：两段手势乐句 + 中段停顿 ----------
    {
        "name": "talk_warm_long_a",
        "type": "talk",
        "emotion": "warm",
        "length": 447,
        "exit_frac": 0.56,
        "motion": (
            "Motion, first half: She speaks with lively warmth, like a gracious hostess "
            "welcoming an old friend. She raises her right hand from her lap with an open, "
            "palm-up presenting gesture, sweeps it gently outward, then brings it to rest "
            "over her heart for a moment. She follows with two soft, friendly nods and a "
            "small tilt of her head, eyes bright. Around the middle of the shot she "
            "lowers her hand back to her lap and holds a brief, still, neutral pause. "
            "Motion, second half: She lifts both hands a little from their resting places "
            "and opens them outward in a warm, welcoming gesture, palms visible, then "
            "lets them float back down. She ends with a slow, pleasant nod, her hand "
            "giving one small open-palm gesture toward the camera, and settles."
        ),
    },
    {
        "name": "talk_warm_long_b",
        "type": "talk",
        "emotion": "warm",
        "length": 447,
        "exit_frac": 0.64,
        "motion": (
            "Motion, first half: She listens and responds with tender, encouraging "
            "energy. She tilts her head to one side with a soft smile, raises her left "
            "hand in a gentle, flowing gesture as if offering something precious, palm "
            "open and relaxed, and lets it drift back down. She gives a slow, comforting "
            "nod. Around the middle of the shot she returns to a brief, still, neutral "
            "pause. Motion, second half: She gestures again with her right hand in a "
            "smooth, inviting arc toward the viewer, then places her hand lightly over "
            "her chest, shoulders relaxing warmly. She finishes with a gentle head tilt "
            "and settles back into the neutral pose."
        ),
    },
    # ---------- 长情绪片段（emphatic） ----------
    {
        "name": "talk_emph_long_a",
        "type": "talk",
        "emotion": "emphatic",
        "length": 447,
        "exit_frac": 0.6,
        "motion": (
            "Motion, first half: She explains something important with focused, confident "
            "energy. She leans her upper body slightly toward the camera, raises her right "
            "hand and presses her palm down twice in a firm, measured emphasis gesture, "
            "then raises her index finger to underscore a key point. She gives two "
            "deliberate nods. Around the middle of the shot she sits back upright, lowers "
            "her hand and holds a brief, still, neutral pause. Motion, second half: She "
            "leans in again and counts off two points on her fingers with crisp, clean "
            "motions, then concludes with one firm palm-down press and a steady, assured "
            "gaze into the camera, returning to the neutral pose."
        ),
    },
    {
        "name": "talk_emph_long_b",
        "type": "talk",
        "emotion": "emphatic",
        "length": 447,
        "exit_frac": 0.58,
        "motion": (
            "Motion, first half: Her expression is serious and composed, shoulders "
            "squared. She uses her right hand in a decisive, flat chopping gesture to "
            "mark her point, then opens the same hand palm-up in a challenging, "
            "here-is-the-fact gesture. Her chin stays level, her gaze steady on the "
            "camera. Around the middle of the shot she lowers her hand and holds a "
            "brief, still, neutral pause. Motion, second half: She raises her hand once "
            "more, palm facing the camera in a firm hold-on gesture, then points forward "
            "gently with her index finger for final emphasis, gives one slow, deliberate "
            "nod, and returns to the neutral pose."
        ),
    },
]

# v2 头像包 = v1 全部片段 + v2 新增
CLIPS = list(_V1_CLIPS) + CLIPS_V2

ANCHOR = ANCHOR
