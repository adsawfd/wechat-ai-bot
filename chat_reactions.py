"""Recognize text-channel WeChat face codes and Unicode emoji reactions."""
import re

_NAMES = '''微笑 撇嘴 色 发呆 得意 流泪 害羞 闭嘴 睡 大哭 尴尬 发怒 调皮 呲牙 惊讶 难过 酷 冷汗 抓狂 吐 偷笑 可爱 白眼 傲慢 饥饿 困 惊恐 流汗 憨笑 大兵 奋斗 咒骂 疑问 嘘 晕 疯了 衰 骷髅 敲打 再见 擦汗 抠鼻 鼓掌 糗大了 坏笑 左哼哼 右哼哼 哈欠 鄙视 委屈 快哭了 阴险 亲亲 吓 可怜 菜刀 西瓜 啤酒 篮球 乒乓 咖啡 饭 猪头 玫瑰 凋谢 示爱 爱心 心碎 蛋糕 闪电 炸弹 刀 足球 瓢虫 便便 月亮 太阳 礼物 拥抱 强 弱 握手 胜利 抱拳 勾引 拳头 差劲 爱你 NO OK 爱情 飞吻 跳跳 发抖 怄火 转圈 磕头 回头 跳绳 挥手 激动 街舞 献吻 左太极 右太极 脸红 脸红笑 破涕为笑 捂脸 奸笑 机智 皱眉 耶 红包 嘿哈 旺柴 加油 加油加油 社会社会 吃瓜 合十 汪汪 哇 打脸 苦涩 裂开 翻白眼 让我看看 叹气 无语666 天啊 Emm 打Call'''.split()
_CODES = '|'.join(re.escape(name) for name in _NAMES)
_BASE = r'[\U0001f000-\U0001faff\u2300-\u23ff\u2600-\u27bf]'
_REACTION = re.compile(r'(?:(?:\[(?:' + _CODES + r')\])|' + _BASE + r'|[\ufe0e\ufe0f\u200d\u20e3\s])+')


def is_reaction_text(text):
    value = str(text or '').strip()
    return bool(value and _REACTION.fullmatch(value) and (re.search(_BASE, value) or re.search(r'\[', value)))
