# 咖啡厅坐姿角色 · 素材生成提示词

目标角色：中国女性，长相妩媚；白衬衫 + 职业短裙 + 黑丝 + 高跟鞋；坐在咖啡厅沙发上，自然看向镜头。
用途：LiveTalking 的 wav2lip 待机素材（不是最终展示视频，是喂给嘴部驱动的「底片」）。

生成分两步，**两步的提示词不能混用**：

```
文生图（底图）      → 一帧静止画面，定死人物/服装/构图/光线
      ↓
图生视频（动作）    → 在这帧上长出 2~5 秒待机动作，首尾同帧可循环
```

---

## 一、底图提示词（文生图，输出 3:4 竖构图）

```
Photorealistic portrait photograph of a beautiful young Chinese woman in her late twenties,
alluring delicate features, soft makeup with subtle eyeliner, long dark wavy hair falling over
her shoulders. She wears a crisp white silk shirt (top button unfastened, sleeves buttoned at
the wrist), a tailored charcoal grey pencil skirt, sheer black stockings and black high-heeled
pumps. She sits elegantly on a light beige fabric sofa in a cozy upscale coffee shop, legs
crossed at the knee, one forearm resting on the sofa armrest, the other hand resting on her lap.
She looks directly into the camera with a calm, confident, closed-lip smile.

Medium shot, framing from the top of her head down to mid-thigh, subject centered, 3:4 vertical
composition. Soft diffused window light from the front-left, warm ambient café lighting, soft
shadows. Shallow depth of field, background softly blurred: wooden shelves, hanging pendant lamps,
a window with sheer curtains — no people, no customers, no moving objects.

Sharp focus on her face, 85mm lens look, natural skin texture, no heavy retouching.
```

要点：
- **构图取「头顶到大腿中段」**：坐姿下脸高约占画面 30%，正好落在 S3FD 好用、crop 后嘴像素充足的区间
- **正面柔光**：窗光放前侧，别放背后（逆光会让脸一半黑，检测和口型都会退化）
- **背景没人**：咖啡厅人流是静帧循环素材的头号杀手，视频里走过的路人会「原地穿模」
- 服装描述保持职业克制，避免生成过度暴露而影响后续口型稳定性

---

## 二、动作提示词（图生视频，首帧 = 尾帧 = 上面那张图）

```
integrated_multimodal_description: Photorealistic cinematic video, static locked camera,
no camera movement, no zoom, no cuts.

[Shot 1] The same young Chinese woman in a white silk shirt, charcoal pencil skirt and sheer
black stockings sits on a beige sofa in a warm, softly lit coffee shop, facing the camera with
a calm, gentle, closed-lip smile.

Her head stays centered and facing the camera with only tiny, slow, natural micro-movements:
it tilts very slightly to one side and comes back. Her chest and shoulders rise and fall with
slow, relaxed breathing. Her torso sways gently as she shifts her weight on the sofa cushion.
The fingers of her hand on the armrest make small, natural, idle movements; her other hand rests
relaxed on her lap. She blinks naturally twice. Her hair and the fabric of her shirt follow her
small movements naturally. Her crossed legs stay still and elegant the whole time.

Her mouth stays closed throughout — no speech, no talking, no lip movement, no teeth showing.
The background stays perfectly static: no walking people, no moving objects, no flickering lights.
Consistent face, consistent clothing, consistent lighting, no camera movement, no zoom, no cuts.
The first and last frames are identical for seamless looping.
```

动作设计逐条对应素材清单：

| 提示词里的动作 | 为什么这么写 |
|---|---|
| head micro-movements, 轻侧倾再回正 | 头动控制在 ±5°，既不死板又不破坏口型；上下点头幅度要小，容易把脖子拉变形 |
| chest/shoulders 呼吸起伏 | 画面「活着」的主要来源，wav2lip 不碰身体，纯赚 |
| torso sways, 重心微移 | 坐姿最自然的躯干动作，幅度小、不会脱框 |
| 手指小动作（扶手 + 膝上） | 增加「活人感」最有效的一处细节，且完全在脸部 bbox 之外 |
| blinks twice | 眨眼是自然度关键，两次刚好覆盖 5 秒 |
| crossed legs stay still | **腿必须静止**：交叠的腿一旦动，AI 视频容易穿模、膝盖结构崩坏 |
| mouth stays closed / no teeth | 静默期服务端直接显示原帧，素材张嘴就露馅 |
| background perfectly static | 背景有行人/蒸汽/灯闪，循环播放时会「瞬移」 |
| first and last frames identical | 配合管线首尾同帧输入，循环无缝 |

---

## 三、纯 T2V 一步出片（无底图）

没有角色照片时，把「人物 + 场景 + 构图 + 光线 + 动作」合并成一段提示词直接 T2V，
已验证可行（`MiniMaxH3ImageToVideo` 不接 first/last frame 即纯文本条件）：

```bash
PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_video_t2v.py \
  --prompt-file my_tools/prompt_cafe_presenter_t2v.txt \
  --width 864 --height 1152 --length 124 --seed 20261020 --out cafe_t2v_idle
```

配套提示词：`my_tools/prompt_cafe_presenter_t2v.txt`（= 底图的人物/服装/场景/光线
+ 动作段 + **显式构图指令**）。

T2V 的两个硬经验（冒烟测试实测）：

1. **构图指令必须显式写**（"medium shot from head to mid-thigh, face fills about one
   third of the frame height"）。不写的话模型自由发挥成全身景，脸高只有画面 13%，
   crop 后嘴像素不足以做口型（预检 [!] 脸太小）。
2. **seed 决定角色长相**：同一提示词换 seed 就是另一个人。想固定角色就固定 seed；
   想做同一角色的多段动作组，用 T2V 出片后**截一帧当底图转 I2V**（prompt_cafe_presenter.md
   第一、二节的流程），不要再 T2V。

---

## 四、I2V 直接跑生成（有底图时）

底图存好后（建议 3:4，长边 ≥1024）：

```bash
cd /e/work/LiveTalking
PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_idle_video.py \
  --image "E:/work/LiveTalking/my_tools/image/cafe_presenter_base.png" \
  --prompt-file "my_tools/prompt_cafe_presenter.txt" \
  --style natural --length 124 --seed 20261020 \
  --out cafe_presenter_idle
```

生成完 → 预检 → 建头像包：

```bash
# 1. 预检（应全部 [v]：检出稳定 / 脸占比合适 / 头动温和 / 嘴部闭合）
PYTHONPATH= .venv/Scripts/python.exe my_tools/check_source_video.py \
  --video D:/work/AI/ComfyUI/output/video/cafe_presenter_idle_00001.mp4 --plot

# 2. 直接建头像包（不要 stabilize，头动温和时直通最自然）
PYTHONPATH=E:/work/LiveTalking .venv/Scripts/python.exe avatars/wav2lip/genavatar.py \
  --video D:/work/AI/ComfyUI/output/video/cafe_presenter_idle_00001.mp4 \
  --avatar_id cafe_presenter --img_size 256

# 3. 口型 A/B 验证
PYTHONPATH= .venv/Scripts/python.exe my_tools/lipsync_ab_test.py --avatar cafe_presenter
```

---

## 五、验收标准（逐条对）

| 项目 | 达标线 |
|---|---|
| 预检嘴部开合度 p95 | < 0.03（闭嘴素材量级；>0.15 说明在说话） |
| 预检头动 p95 | < 10 px（超过才需要稳定化） |
| 脸高占画面 | 20% ~ 70%（理想 ~30%） |
| 口型 A/B ratio | > 1.5x，且条带目检嘴型随语音开合 |
| 颈部 | 无拉直、无硬边、无重影 |
| 循环接缝 | 首尾帧像素差 < 2 |
