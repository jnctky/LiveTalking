# -*- coding: utf-8 -*-
"""ClipPlan 二期行为自测（不进服务, 纯状态机）。

覆盖:
1. 一期基线: 不传开关时行为不变(talk 片段随机来自全池)
2. 按语义选情绪: emotion=happy -> 只挑 warm 池; 未知情绪 -> 回退全池不报错
3. 按句切音频: 句子边界(seg 变化)在出口帧换 talk, 且不会切在句首第一帧
4. 情绪不认识的容错: clips.json 里没有该情绪时必须还能播

用法: PYTHONPATH=E:/work/LiveTalking .venv/Scripts/python.exe my_tools/clip_plan_test.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from avatars.clip_plan import ClipPlan  # noqa: E402

FPS = 25
META = {
    "fps": FPS,
    "clips": [
        {"name": "idle_a", "type": "idle", "start": 0, "end": 56, "exit": 33},
        {"name": "idle_b", "type": "idle", "start": 56, "end": 112, "exit": 89},
        {"name": "talk_warm_a", "type": "talk", "emotion": "warm",
         "start": 112, "end": 236, "exit": 192},
        {"name": "talk_warm_b", "type": "talk", "emotion": "warm",
         "start": 236, "end": 360, "exit": 316},
        {"name": "talk_emph_a", "type": "talk", "emotion": "emphatic",
         "start": 360, "end": 484, "exit": 440},
    ],
}

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def make_plan():
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(META, f)
    return ClipPlan(path)


def name_at(plan, frame):
    for c in plan.clips:
        if c.start <= frame < c.end:
            return c.name
    return "?"


def talk_names(seen):
    return {n for n in seen if n.startswith("talk")}


def run_utterance(plan, seconds=8.0, seg_marks=None):
    """模拟一次说话: 静默 2s -> 说话 seconds -> 静默 2s。seg_marks={帧偏移: (seg, emotion)}"""
    frames = []
    for _ in range(int(2 * FPS)):
        frames.append(plan.advance(False))
    seg_marks = seg_marks or {}
    for i in range(int(seconds * FPS)):
        if i in seg_marks:
            seg, emotion = seg_marks[i]
            plan.on_segment(seg, emotion, semantic=True, sentence=True)
        frames.append(plan.advance(True))
    speak = list(frames[int(2 * FPS):])
    for _ in range(int(2 * FPS)):
        frames.append(plan.advance(False))
    return speak, [name_at(plan, f) for f in frames]


def scenario_baseline():
    print("\n[1] 一期基线: 无开关")
    plan = make_plan()
    speak, _ = run_utterance(plan, 8.0)
    names = [name_at(plan, f) for f in speak]
    used = talk_names(names)
    check(used and all(n.startswith("talk") for n in names), f"说话期全在 talk 片段, 实际 {used}")
    check(len(used) <= 2, f"8s 内最多换 1 次段, 实际用到 {sorted(used)}")


def scenario_emotion():
    print("\n[2] 按语义选情绪 (happy -> warm)")
    plan = make_plan()
    speak, _ = run_utterance(plan, 10.0, {0: ("s1", "happy")})
    names = [name_at(plan, f) for f in speak]
    used = talk_names(names)
    check(used and all(n.startswith("talk_warm") for n in used),
          f"只应使用 warm 池, 实际 {sorted(used)}")

    print("\n[2b] 未知情绪需要回退而不是卡死")
    plan = make_plan()
    speak, _ = run_utterance(plan, 10.0, {0: ("s1", "no-such-emotion")})
    names = [name_at(plan, f) for f in speak]
    used = talk_names(names)
    check(bool(used), f"未知情绪仍应有 talk 片段, 实际 {sorted(used)}")


def scenario_sentence():
    print("\n[3] 按句切音频: 第二句开始换段")
    plan = make_plan()
    # 第一句情绪 warm, 2.4s 后第二句 emphatic
    speak, _ = run_utterance(plan, 9.0, {0: ("s1", "happy"), int(2.4 * FPS): ("s2", "angry")})
    names = [name_at(plan, f) for f in speak]
    used = talk_names(names)
    check("talk_warm_a" in used or "talk_warm_b" in used, f"第一句用 warm, 实际 {sorted(used)}")
    check(any(n == "talk_emph_a" for n in names), f"第二句应切到 emphatic, 实际 {sorted(used)}")

    # 切换点必须落在出口帧之后(不会一有新句就硬切)
    first_emph = next(i for i, n in enumerate(names) if n == "talk_emph_a")
    check(first_emph >= int(2.4 * FPS) - 1,
          f"切换不早于句子边界 (第 {first_emph} 帧 >= {int(2.4 * FPS)})")
    check(first_emph <= int(2.4 * FPS) + int(1.5 * FPS),
          f"切换延迟 <=1.5s (第 {first_emph} 帧)")

    print("\n[3b] 关闭按句切换: 新句只换情绪, 不主动换段")
    plan = make_plan()
    for _ in range(int(2 * FPS)):
        plan.advance(False)
    plan.on_segment("s1", "happy", semantic=True, sentence=False)
    names = []
    for i in range(int(9 * FPS)):
        if i == int(2.4 * FPS):
            plan.on_segment("s2", "angry", semantic=True, sentence=False)
        names.append(name_at(plan, plan.advance(True)))
    # 5s 的片段在 9s 内自然播完一次, 换段是 _on_end 的功劳, 不是句子边界
    check(len(talk_names(names)) <= 2, f"最多自然换 1 次段, 实际 {sorted(talk_names(names))}")


def scenario_repeat_seg():
    print("\n[4] 同一个 seg 重复上报(批次内重复) 无副作用")
    plan = make_plan()
    for _ in range(int(2 * FPS)):
        plan.advance(False)
    plan.on_segment("s1", "happy", semantic=True, sentence=True)
    before = plan.segment_id
    for _ in range(5):
        plan.on_segment("s1", "happy", semantic=True, sentence=True)
    check(plan.segment_id == before, "seg 未变化时状态保持不变")


if __name__ == "__main__":
    scenario_baseline()
    scenario_emotion()
    scenario_sentence()
    scenario_repeat_seg()
    print("\n=== %s ===" % ("全部通过" if not fails else f"{len(fails)} 项失败"))
    sys.exit(0 if not fails else 1)
