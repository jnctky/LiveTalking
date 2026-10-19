# 模型权重下载与校验

主权重（`wav2lip.pth`、头像包）见 [README 第 2.1 节](../README.md#21-下载模型)。
本文档记录另外需要手动准备、且**不入库**的权重文件。

## s3fd.pth（S3FD 人脸检测权重）

| 项 | 值 |
|---|---|
| 用途 | 头像生成流程中的人脸检测与关键点对齐：`avatars/wav2lip/genavatar.py`、`avatars/wav2lip/inference_silence.py`、Web 端 `/avatar.html` 上传视频 |
| 放置路径 | `avatars/wav2lip/face_detection/detection/sfd/s3fd.pth` |
| 大小 | 89,843,225 字节（≈ 85.7 MiB） |
| SHA-256 | `619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543` |
| 是否必需 | 只在**生成/重建头像**时需要；用 `data/avatars/` 里已有的头像做推理时不加载 |

### 为什么建议手动下载

`avatars/wav2lip/face_detection/detection/sfd/sfd_detector.py` 在文件缺失时会自动执行：

```python
torch.utils.model_zoo.load_url('https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth')
```

问题有两个：

1. `adrianbulat.com` 在国内网络经常超时，头像生成会卡在初始化；
2. `load_url` 把文件缓存到 torch hub 目录（`~/.cache/torch/hub/checkpoints/`），
   **不会**写回上面的 `s3fd.pth` 路径，所以下次重建头像还会再拉一遍。

手动放一份到位就能彻底绕开。

### 下载

```bash
cd /e/work/LiveTalking   # 项目根

# 方式 1：HuggingFace 镜像（推荐，国内可直连）
curl -L -o avatars/wav2lip/face_detection/detection/sfd/s3fd.pth \
  https://hf-mirror.com/yiliAST/livetalking-assets/resolve/main/models/hub/checkpoints/s3fd-619a316812.pth

# 方式 2：官方源（需能访问 adrianbulat.com）
curl -L -o avatars/wav2lip/face_detection/detection/sfd/s3fd.pth \
  https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth

# 方式 3：断点续传 / 多线程（本机已装 aria2c）
aria2c -x 16 -s 16 \
  -d avatars/wav2lip/face_detection/detection/sfd -o s3fd.pth \
  https://hf-mirror.com/yiliAST/livetalking-assets/resolve/main/models/hub/checkpoints/s3fd-619a316812.pth
```

### 校验

```bash
sha256sum avatars/wav2lip/face_detection/detection/sfd/s3fd.pth
# 期望输出：
# 619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543
```

大小对但 SHA-256 不对，通常是被截断，或者镜像返回了 HTML 错误页 —— 删掉重下即可。

### 备注

- musetalk 模型使用同一份权重，路径为
  `avatars/musetalk/utils/face_detection/detection/sfd/s3fd.pth`；
  只在跑 musetalk 时才需要，`.gitignore` 的 `s3fd*.pth` 规则同样覆盖它。
- 该权重已加入 `.gitignore`（约 86MB 的第三方权重），不要提交到仓库，
  也不要用 `git add -A` 批量提交。
