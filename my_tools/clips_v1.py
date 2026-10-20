# -*- coding: utf-8 -*-
"""一期多片段定义（多动作组互切实验）。

设计约定（与用户确认的方案一致）：
- 所有片段共用同一个「起点帧」（anchor）：_anchor.png，取自 cafe_t2v_idle 第 0 帧
- 每个片段 first_frame == last_frame == 起点帧 => 首尾可无缝互切
- 嘴全程闭合（静默期原帧直出、说话期嘴部由 wav2lip 重绘，情绪只能靠身体表达）
- length 必须满足 17k+5 网格：56 帧=2.33s，124 帧=5.17s @24fps
"""

BASE = (
    "integrated_multimodal_description: Photorealistic cinematic video, static locked camera, "
    "no camera movement, no zoom, no cuts. "
    "[Shot 1] A beautiful young Chinese woman in her late twenties, alluring delicate features, "
    "soft makeup with subtle eyeliner, long dark wavy hair falling over her shoulders. "
    "She wears a crisp white silk shirt (top button unfastened, sleeves buttoned at the wrist), "
    "a tailored charcoal grey pencil skirt, sheer black stockings and black high-heeled pumps. "
    "She sits elegantly on a light beige fabric sofa in a cozy upscale coffee shop, legs crossed "
    "at the knee, one forearm resting on the sofa armrest, the other hand resting on her lap. "
    "She looks directly into the camera. "
    "Framing: medium shot from the top of her head down to mid-thigh, subject centered, 3:4 "
    "vertical composition. Lighting: soft diffused window light from the front-left, warm ambient "
    "cafe lighting, soft shadows. Background softly blurred: wooden shelves, hanging pendant lamps, "
    "a window with sheer curtains, no people, no customers, no moving objects. "
)

TAIL = (
    " She starts from a still, neutral seated pose and returns to exactly the same still, neutral "
    "seated pose at the end of the shot. Her mouth stays closed throughout, no speech, no talking, "
    "no lip movement, no teeth showing, no laughing. Her hands never cover or touch her face. "
    "The background stays perfectly static: no walking people, no moving objects, no flickering "
    "lights. Consistent face, consistent clothing, consistent lighting, no camera movement, "
    "no zoom, no cuts. The first and last frames are identical for seamless looping."
)

# type: idle=待机轮播 / talk=说话期动作（emotion 用于二期语义选择）
CLIPS = [
    {
        "name": "idle_a",
        "type": "idle",
        "emotion": "",
        "length": 56,
        "motion": (
            "Motion: She breathes slowly and naturally, her chest and shoulders rising and "
            "falling gently. She blinks naturally twice. Her head tilts very slightly to one "
            "side and comes back to center."
        ),
    },
    {
        "name": "idle_b",
        "type": "idle",
        "emotion": "",
        "length": 56,
        "motion": (
            "Motion: The fingers of her hand on the armrest make small, natural, idle "
            "movements, and she shifts her weight slightly on the sofa cushion, her torso "
            "swaying very gently. She blinks once."
        ),
    },
    {
        "name": "idle_c",
        "type": "idle",
        "emotion": "",
        "length": 56,
        "motion": (
            "Motion: Her gaze drifts briefly to the side as if thinking, then back to the "
            "camera. Her closed-lip smile deepens a little. She gives one very slow, tiny nod "
            "and returns to stillness."
        ),
    },
    {
        "name": "talk_warm_a",
        "type": "talk",
        "emotion": "warm",
        "length": 124,
        "motion": (
            "Motion: She holds a warm, friendly smile with relaxed, bright eyes, like a "
            "gracious host welcoming a guest. Her head tilts slightly to one side with "
            "interest and returns. She lifts her free hand a little from her lap in a small, "
            "soft, open palm-up gesture, then lowers it back down. Her shoulders stay relaxed."
        ),
    },
    {
        "name": "talk_warm_b",
        "type": "talk",
        "emotion": "warm",
        "length": 124,
        "motion": (
            "Motion: She keeps a gentle, encouraging smile. She gives two small, slow, "
            "conversational nods, her head tilting softly with them. Her torso leans back "
            "very slightly into the sofa in a relaxed, open posture, then settles."
        ),
    },
    {
        "name": "talk_emph_a",
        "type": "talk",
        "emotion": "emphatic",
        "length": 124,
        "motion": (
            "Motion: Her expression turns focused and attentive, eyebrows slightly drawn, "
            "chin level, like she is explaining something important. She leans her upper "
            "body slightly forward toward the camera, her hand on the armrest gives one soft "
            "emphasis tap, then she returns upright."
        ),
    },
    {
        "name": "talk_emph_b",
        "type": "talk",
        "emotion": "emphatic",
        "length": 124,
        "motion": (
            "Motion: Her expression is serious and composed, head straight, shoulders "
            "squared with confident energy. She gives two slow, deliberate nods with firm "
            "emphasis, pauses, then returns to the neutral pose. Her hand on the armrest "
            "stays quiet."
        ),
    },
]

ANCHOR = r"my_tools/image/clips/_anchor.png"
