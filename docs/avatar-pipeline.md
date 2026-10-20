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
