# -*- coding: utf-8 -*-
"""多片段播放计划（clips.json 驱动的帧调度器）。

头像包可选附带 clips.json，描述拼接长序列里的片段边界：
{
  "fps": 25,
  "clips": [
    {"name": "idle_a", "type": "idle",  "start": 0,  "end": 55,  "exit": 40},
    {"name": "talk_warm_a", "type": "talk", "emotion": "warm",
     "start": 56, "end": 179, "exit": 130}
  ]
}

约定:
- start/end/exit 为拼接后全局帧号, 区间 [start, end)
- 所有片段首尾帧均为同一「起点帧」=> 跨片段硬切几乎无感
- exit 为「出口帧」: 说话开始/结束时等到该帧再切换, 兼顾「播完当前动作」
  与「响应延迟」(exit 越靠后越接近播完整段); 片段内偏移 = exit - start

播放规则(一期):
- 静默: 待机片段洗牌袋轮播, 播完一段才换下一段(不重复、不倒放)
- 说话开始: 等当前待机播到出口帧 -> 切入 talk 洗牌袋下一段
- 说话结束: 等当前 talk 播到出口帧 -> 回待机(片段尾部=起点帧, 硬切无感)
- talk 播完话没完: 同洗牌袋切下一段 talk(避免同段动作重复)
- forward-only: 帧号单调推进, 不做正反往复(mirror)
"""

import json
import random

from utils.logger import logger


class _Clip:
    __slots__ = ("name", "type", "emotion", "start", "end", "exit")

    @property
    def length(self):
        return self.end - self.start


class ClipPlan:
    def __init__(self, meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.fps = int(meta.get("fps", 25))
        clips = []
        for d in meta["clips"]:
            c = _Clip()
            c.name = d["name"]
            c.type = d.get("type", "idle")
            c.emotion = d.get("emotion", "")
            c.start = int(d["start"])
            c.end = int(d["end"])
            # exit 允许全局帧号或片段内偏移: >= start 视为全局, 否则视为偏移
            ex = int(d.get("exit", c.end - 3))
            if ex >= c.start:
                ex -= c.start
            c.exit = max(0, min(ex, c.end - c.start - 3))
            clips.append(c)
        if not clips:
            raise ValueError("clips.json 无片段")
        self.clips = clips
        self.idle_clips = [c for c in clips if c.type == "idle"]
        self.talk_clips = [c for c in clips if c.type == "talk"]
        if not self.idle_clips:
            raise ValueError("clips.json 缺少 idle 片段")

        # 播放状态
        self.mode = "idle"
        self.cur = None
        self.pos = 0
        self._pending = None      # "idle" | 待切入的 _Clip
        self._idle_bag = []
        self._talk_bag = []
        self._pick_idle()
        logger.info("clip_plan: %d clips (%d idle / %d talk), 从 %s 开始",
                    len(clips), len(self.idle_clips), len(self.talk_clips), self.cur.name)

    # ---------- 洗牌袋: 一批洗牌依次播, 播完再洗, 避免连续重复 ----------
    def _draw(self, bag, items):
        if not bag:
            bag[:] = list(items)
            random.shuffle(bag)
        return bag.pop()

    def _pick_idle(self):
        self.cur = self._draw(self._idle_bag, self.idle_clips)
        self.pos = 0
        self.mode = "idle"

    def _choose_talk(self):
        if not self.talk_clips:
            return None
        return self._draw(self._talk_bag, self.talk_clips)

    def _enter(self, clip):
        self.cur = clip
        self.pos = 0
        self.mode = clip.type

    # ---------- 调度 ----------
    def advance(self, speaking):
        """推进一帧, 返回全局帧号。speaking 为当前音频批是否在说话。"""
        self._update(speaking)
        frame = self.cur.start + self.pos
        self.pos += 1
        if self.pos >= self.cur.length:
            self._on_end(speaking)
        return frame

    def _update(self, speaking):
        if self.mode == "idle" and speaking:
            # 说话开始: 记下目标 talk 片段, 等当前待机播到出口帧再切
            if self._pending is None:
                self._pending = self._choose_talk()
            if self._pending is not None and self.pos >= self.cur.exit:
                self._enter(self._pending)
                self._pending = None
        elif self.mode == "talk" and not speaking:
            # 说话结束: 等当前 talk 播到出口帧后回待机
            if self._pending is None:
                self._pending = "idle"
            if self.pos >= self.cur.exit:
                self._pick_idle()
                self._pending = None

    def _on_end(self, speaking):
        if self.mode == "idle":
            self._pick_idle()
        else:
            nxt = self._choose_talk()
            if nxt is None:
                self._pick_idle()
            else:
                self._enter(nxt)
