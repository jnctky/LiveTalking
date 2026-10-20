# -*- coding: utf-8 -*-
"""my_tools 产物目录约定（自写脚本统一从这里取路径）。

    my_tools/
    ├─ log/    运行日志（*.log）
    ├─ image/  可视素材：抓帧、冒烟截图、候选视频（png / jpg / mp4）
    └─ _tmp/   纯临时文件：下载包、调试 dump、一次性探测输出，可随时整目录删

规矩：不允许再把任何文件直接丢在 my_tools/ 根下或项目根下；
临时文件一律落 _tmp/，别再出现 _objinfo.json / _cuda_check.txt 这类根级残留。

用法：
    from paths import LOG_DIR, IMAGE_DIR, TMP_DIR
    out = TMP_DIR / "probe.json"
"""
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent

LOG_DIR = TOOLS_DIR / "log"
IMAGE_DIR = TOOLS_DIR / "image"
TMP_DIR = TOOLS_DIR / "_tmp"


def ensure(*dirs):
    """确保目录存在（默认创建 log / image / _tmp 三个），返回路径列表。"""
    targets = dirs or (LOG_DIR, IMAGE_DIR, TMP_DIR)
    for d in targets:
        Path(d).mkdir(parents=True, exist_ok=True)
    return [Path(d) for d in targets]
