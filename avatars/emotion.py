# -*- coding: utf-8 -*-
"""情绪标签与句子切分（服务端 TTS 路径用）。

两条链路都要给多片段头像喂「这句话是什么情绪」：

1. airi → /humanaudio：情绪由前端的 ACT 信号给出，服务端原样透传，
   只需 EMOTION_ALIASES 把前端词表映射到 clips.json 的 emotion 值。
2. /human 文本 → 服务端 TTS：没有现成情绪，用关键词规则粗分类。
   规则分类只求「大致对」，宁可回退到无偏好（随机挑），也不要乱猜。

注意：情绪只影响「选哪一段动作」，不影响口型。wav2lip 会按音频重绘整张脸，
嘴部表情演不出来，情绪必须靠身体语言（前倾/点头/抬手）表达——这也是
对话片段素材要求闭嘴的原因。
"""

import re

# 前端（airi）情绪词表 → clips.json 里的 emotion 值。
# 值为空串表示「没有偏好」，交给洗牌袋随机挑。
EMOTION_ALIASES = {
    # 亲和/温和
    "happy": "warm",
    "joy": "warm",
    "calm": "warm",
    "gentle": "warm",
    "tender": "warm",
    "sad": "warm",
    "curious": "warm",
    "awkward": "warm",
    # 强调/认真
    "angry": "emphatic",
    "serious": "emphatic",
    "emphatic": "emphatic",
    "think": "emphatic",
    "surprised": "emphatic",
    "question": "emphatic",
    # 中性：不指定情绪
    "neutral": "",
    "": "",
}

# 文本规则分类用的关键词。命中越多越优先；打平则不指定情绪。
_KEYWORDS = {
    "warm": (
        "很高兴", "开心", "欢迎", "喜欢", "感谢", "谢谢", "太好了",
        "亲爱的", "温柔", "陪你", "慢慢", "别担心", "没关系", "辛苦", "期待",
    ),
    "emphatic": (
        "一定", "必须", "重要", "注意", "关键", "其实", "绝不", "千万",
        "认真", "强调", "记住", "说到底", "重点是", "问题是", "千万不",
    ),
}

_SENT_END = re.compile(r"(?<=[。！？!?…；;])")
_TRAILING = " \t\r\n\"'”’)）】]"


def normalize(emotion) -> str:
    """前端情绪词归一化；未知词保留原样（便于 clips.json 直接用同名词）。"""
    if not emotion:
        return ""
    return str(emotion).strip().lower()


def resolve(emotion, available=()) -> str:
    """把任意情绪词映射到当前 clips.json 里真实存在的 emotion 值。

    找不到对应值时返回空串 = 不指定偏好。
    """
    e = normalize(emotion)
    if not e:
        return ""
    if not available or e in available:
        return e
    alias = EMOTION_ALIASES.get(e, "")
    if alias and (not available or alias in available):
        return alias
    return ""


def split_sentences(text, min_len=4, max_len=120):
    """按句末标点切句。过短的句子并入上一句，过长的按逗号再切。

    TTS 一句一段的好处：每句音频 3~6 秒，与 talk 片段（约 5 秒）天然对齐，
    动作切换落在句子边界而不是句子中间。
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip(_TRAILING) for p in _SENT_END.split(text)]
    parts = [p for p in parts if p]
    if not parts:
        return [text]

    out = []
    for p in parts:
        if out and len(p) < min_len:
            out[-1] = out[-1] + p
        elif len(p) > max_len:
            # 超长句按逗号/顿号再切，避免一句音频过长
            buf = ""
            for piece in re.split(r"(?<=[，,、：:])", p):
                if buf and len(buf) + len(piece) > max_len:
                    out.append(buf)
                    buf = piece
                else:
                    buf += piece
            if buf:
                out.append(buf)
        else:
            out.append(p)
    return out


def classify(text) -> str:
    """关键词规则分类，返回 "warm" / "emphatic" / ""（无偏好）。"""
    t = text or ""
    if not t:
        return ""
    scores = {k: sum(1 for w in words if w in t) for k, words in _KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return ""
    # 打平则不指定，避免随机偏向
    if list(scores.values()).count(scores[best]) > 1:
        return ""
    return best
