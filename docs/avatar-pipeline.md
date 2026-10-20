# 头像生成管线（Avatar Pipeline）

本文说明如何把一段真人视频做成 wav2lip 可驱动的头像包，以及**必须使用官方
`avatars/wav2lip/genavatar.py`** 的原因。后者是血泪教训，见文末「为什么不要自写裁剪」。

## 一、目录结构

一个头像包（`data/avatars/<avatar_id>/`）只有三样东西：

```
data/avatars/<avatar_id>/
├── full_imgs/      # 原始帧（PNG），推理时作为贴回底图
├── face_imgs/      # 裁剪并对齐的人脸（PNG，img_size × img_size）
└── coords.pkl      # 每帧人脸框 (y1, y2, x1, x2)，贴回位置
```

三者帧数必须一致，文件名按数字递增（`00000000.png` …）。推理时按
`mirror_index` 正反往复播放：`0 → 末帧 → 0`，因此素材**不需要**做成首尾同帧。

## 二、标准生成命令

```bash
# 在项目根执行；PYTHONPATH 必须是项目根，否则 import avatars 会失败
PYTHONPATH=. .venv/Scripts/python.exe avatars/wav2lip/genavatar.py \
    --video  input.mp4 \
    --avatar_id my_avatar \
    --img_size 256
```

关键默认值（不要随意改）：

| 参数 | 默认 | 作用 |
|---|---|---|
| `--img_size` | 96 | 输出人脸边长。本项目统一用 **256**（与官方 `wav2lip256_avatar1` 及现有头像一致） |
| `--pads` | `[0, 10, 0, 0]` | 人脸框扩展 (top, bottom, left, right)。只向下补 10px 保证含下巴，**左右不扩** |
| `--nosmooth` | 关 | 默认对检测框做 T=5 帧平滑，抑制框抖动 |
| `--face_det_batch_size` | 16 | OOM 时脚本会自动减半重试 |

生成后的自检：`coords.pkl` 里框的宽高比应稳定在 **w/h ≈ 0.7**（竖长形人脸框），
帧间位移只有几个像素。若看到正方形框或比例接近 1.0，说明裁剪逻辑被改坏了。

## 三、对素材的要求

| 项 | 建议 |
|---|---|
| 相机 | 固定机位，不推拉摇移 |
| 朝向 | 正脸，侧转不超过 15° |
| 嘴部 | 无遮挡（手、麦、烟雾都不行），说话时保持闭合微笑 |
| 时长 | 5–20 秒（帧数 = 时长 × fps，不锁死） |
| 分辨率 | 720p 以上，人脸在画面里越大越好 |
| 光照 | 稳定，避免忽明忽暗 |

## 四、头部动作与稳定化后处理

wav2lip 的输出是**整张人脸**并整块贴回 bbox 区域，所以它并不要求头部完全静止；
官方示例本身也有轻微头部移动。但**较大的头部转动/位移**会让逐帧 bbox 漂移，
贴回时下巴边缘对不齐，出现变形。

如果素材动作较大，先做头部稳定化再生成头像：

```bash
PYTHONPATH= .venv/Scripts/python.exe my_tools/stabilize_head.py \
    --video raw.mp4 --out stab.mp4
```

它逐帧把头部对齐回基准位置，身体动作（肩颈、重心）保留。处理后可用 S3FD
复检：框中心漂移应从 ±10px 级降到 ±5px 级。

## 五、为什么不要自写裁剪（重要）

推理侧 `avatars/wav2lip_avatar.py` 的实际行为：

```python
img_masked = img_batch.copy()
img_masked[:, face.shape[0] // 2:] = 0            # 模型输入通道 1：下半脸置零
img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.   # 6 通道
pred = self.model(audiofeat_batch, img_batch)     # 输出整脸
...
combine_frame[y1:y2, x1:x2] = res_frame           # 整个 bbox 区域替换
```

两点推论：

1. 模型**能看到完整人脸**（通道 2 是原图），输出也是完整人脸，嘴在 crop 的
   什么位置都能被重建——不存在"某个区域不会被重建"的说法。
2. 贴回是**整块替换**。因此 crop 里除脸以外的内容（头发、背景、肩膀）全部
   由模型幻想生成；crop 里脸越小，嘴部有效像素越少，口型越糊、周边伪影越重。

**正确构图 = 人脸特写占满画面**（S3FD 竖长框直接用）。曾经自写脚本做过
「正方形化 + 1.08 倍扩边 + 嘴部锚点对齐」，结果 crop 变成头肩中景，嘴部
只剩约 30px，表现为「嘴不张 + 下巴变形」——而且用帧差统计（嘴部 mean 3+）
还看不出来，必须看特写连拍才能发现。

结论：**裁剪只走官方 `genavatar.py`，不要自己写**。官方把竖长框拉伸成方形
（宽高比 0.7 → 1.0）是训练分布的一部分，不要"修正"成等比例裁剪。

## 六、生成后验证

```bash
# 口型是否跟随语音（嘴部帧差 vs 全图帧差）
PYTHONPATH= .venv/Scripts/python.exe my_tools/lipsync_test.py --avatar <avatar_id>

# 说话帧特写：眼睛看嘴型是否有张合，下巴是否有变形
# lipsync_test 输出 my_tools/_talk_*.png
```

判读口径：嘴部帧差明显高于全图帧差只是必要条件；**必须目视特写确认嘴有张合**。
头部动作会污染帧差，同条件对比（同一段文本、同一 avatar 尺寸）才有意义。

## 七、切换 / 使用

服务端 `build_avatar_session()` 支持按请求指定头像，因此不需要重启服务：

- `GET /api/avatars` 列出 `data/avatars/` 下所有头像（帧数、时长）
- `GET /api/avatars/<id>/preview` 返回首帧缩略图
- `POST /offer` body 里带 `"avatar": "<id>"` 即按该头像建会话（不传则用 `--avatar_id`）

airi 侧在「设置 → 角色模型 → LiveTalking → 头像」下拉里选择。

## 八、多片段头像（多动作组）

单条长序列循环看久了会有明显的周期感。多片段方案把「一个待机循环」升级为
「一组可互切的短动作」，静默时轮播、说话时切到对话动作，口型始终由语音驱动。

**核心约定：所有片段的首尾帧都是同一个「起点帧」。** 这让片段之间可以硬切
（起止姿态完全一致，观感上就是"动作接动作"），也让 coords 在段边界几乎连续
（实测拼接后段边界坐标变化 ≤1px，贴回不跳位）。

| 片段类型 | 时长 | 帧数（24fps 生成） | 内容要求 |
|---|---|---|---|
| `idle` 待机 | 2~3s | 56（17k+5 网格） | 呼吸/眨眼/微侧倾/手指小动作，幅度小 |
| `talk` 对话 | 5~6s | 124 | 情绪靠身体/头/眉眼表达，**嘴保持闭合** |

为什么 talk 片段嘴也要闭合：静默期服务端直接显示素材原帧不推理，说话期嘴部
由 wav2lip 重绘。素材本身在说话会导致"无声张嘴"和口型糊掉。

### 生成流程

```bash
# 1) 定义片段：编辑 my_tools/clips_v1.py（BASE 人物场景 + 每段 motion + length）
#    起点帧取自动作素材的第 0 帧，建议放 my_tools/image/clips/_anchor.png
# 2) 批量生成（每段是一段首尾同帧的 I2V，同 seed 保证人物一致）
PYTHONPATH= .venv/Scripts/python.exe my_tools/gen_clip_set.py
# 3) 拼接 → genavatar → 写 clips.json
PYTHONPATH= .venv/Scripts/python.exe my_tools/build_clip_avatar.py --avatar-id <avatar_id>
```

`build_clip_avatar.py` 会自动算每段的**出口帧**（exit）：动作已回到中性、可安全
切出的位置。idle 片段动作幅度小、差异曲线全程低，固定取 60%；talk 片段按与起点帧
的差异曲线取尾部回归点（实测约 65%）。

### clips.json 与播放规则

`data/avatars/<id>/clips.json`（由 build 脚本生成，不要手改帧号）：

```json
{"fps": 25, "forward_only": true,
 "clips": [{"name": "idle_a", "type": "idle", "start": 0, "end": 56, "exit": 33},
           {"name": "talk_warm_a", "type": "talk", "emotion": "warm",
            "start": 168, "end": 292, "exit": 248}]}
```

`start`/`end`/`exit` 都是拼接后的全局帧号。调度器在 `avatars/clip_plan.py`：

- **静默**：待机片段洗牌袋轮播，一段播完才换，不会连续重复
- **说话开始**：等当前待机播到出口帧再切进 talk（延迟 ≤ 约 1.3s，比"必须播完整段"短）
- **说话结束**：talk 播到出口帧后回待机（已过出口帧则立即切）
- **话比片段长**：talk 播完自动换同池下一段，避免同一动作重复
- **forward-only**：帧号单调推进，不再正反往复（倒放会让点头变抬头）

没有 clips.json 的头像行为完全不变（老的 `mirror_index` 循环）。

### 验证

```bash
# 口型 A/B（静默基线 vs 说话，条带图目检开合节奏）
PYTHONPATH= .venv/Scripts/python.exe my_tools/lipsync_ab_test.py --avatar <avatar_id> --speak-seconds 12
node my_tools/airi_cafe_check.js <avatar_id>   # 浏览器端到端：下拉/切换/视频流/播放帧
```

多片段素材的静默底噪很低，A/B 的 ratio 通常 ≥10x（单序列约 1.5~2x），
出现异常低值先怀疑测量（嘴部窗口是否落在嘴上）。

### 扩展方向

- 加片段：往 `clips_v1.py` 追加条目 → 重跑 gen_clip_set（只生成新增的，用 `--only`）→ 重跑 build
- 按语义选情绪：`clips.json` 已有 `emotion` 字段，接 LLM 标签后传给调度器即可（二期）
- 按句切音频：让每句 3~6s，与 talk 片段天然对齐，避免循环感（二期）

### 二期：按语义选情绪 / 按句切音频（已实现）

两个功能都由客户端逐请求携带开关（airi 设置页「LiveTalking」下两个开关，
随每段语音上传），**不传时行为与一期完全一致**：

- **按语义选情绪**：每段语音带 `emotion` 标签（airi 的 ACT 情绪信号，或
  `/human` 传参），服务端用 `avatars/emotion.py` 的别名表归一到 clips.json
  里真实存在的 emotion 值，talk 片段只在同情绪池里挑；匹配不上就回退全池，
  绝不会因为情绪词不认识而没片段可播。`neutral` 及未知词 = 无偏好。
- **按句切音频**：每句语音带唯一 `seg` 标识。同一句的所有音频帧共用一个
  seg，seg 变化 = 句子边界，调度器在出口帧换一段 talk（动作切换落在句子
  之间而不是句中）。airi 的 TTS 分句器本来就按标点切，clip.id 直接当 seg。

接口约定（`/human` JSON / `/humanaudio` 表单字段一致）：

| 字段 | 含义 |
|---|---|
| `emotion` | 情绪标签（happy/angry/…，别名表见 avatars/emotion.py） |
| `seg` | 句子标识，同句相同、跨句不同 |
| `semantic_emotion` | `'1'/'0'`，按语义选情绪开关 |
| `sentence_split` | `'1'/'0'`，按句切音频开关 |

服务端 TTS 路径（`/human` + `--tts`）在 `sentence_split` 开启时自动按句切分
入队（`avatars/emotion.py` 的关键词规则顺带给每句粗分类情绪）；chat 模式的
LLM 流式输出本来就按标点分段，同样逐段带 seg。

验证：

```bash
# 状态机单元自测(情绪过滤/句边界/回退)
PYTHONPATH=E:/work/LiveTalking .venv/Scripts/python.exe my_tools/clip_plan_test.py
# 模拟 airi 链路: 逐句 edge-tts 合成 -> /humanaudio 带元数据上传 -> 核对调度日志
PYTHONPATH= .venv/Scripts/python.exe my_tools/humanaudio_probe.py --avatar cafe_clips --semantic --sentence-split
```

