"""Render code-drawn reaction cards for optional image replies."""
import hashlib
import re
from pathlib import Path

KINDS = {'得意', '大笑', '捂脸', '生气', '疑惑', '点赞'}
MEDIA_STYLE = '''
日常聊天默认用纯文字，不需要每句都加emoji或微信表情。
只有表情能明显传达当下语气时，才偶尔选择文字加表情或单独emoji；不要连续几次使用表情，每次最多一个。
文字表情可用少量常见微信代码[捂脸]、[偷笑]、[笑哭]、[旺柴]、[机智]，或😂😏🙄👍等emoji。
严肃问题、事实解释和安慰优先用纯文字；很短的玩笑反应才可只回一个emoji。
适合玩笑互动、想表达强烈反应或对方索要表情包时，可改为只输出一条：
[[表情包:情绪|短句]]
情绪只能选“得意、大笑、捂脸、生气、疑惑、点赞”，短句不超过16个字，按聊天内容新写。
例如[[表情包:得意|这波没毛病]]。程序会将其渲染成图片发送；不要同时附其他文字。
不要把严肃解释、查到的事实或安慰长文变成图片。不要输出文件路径、图片网址或其他格式。
'''


def render_card(kind, caption, output_dir=None):
    from PIL import Image, ImageDraw, ImageFont
    folder = Path(output_dir) if output_dir else Path(__file__).parent / 'reaction_cards'
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((kind + '\n' + caption).encode()).hexdigest()[:20]
    path = folder / ('reaction_' + key + '.png')
    if path.exists():
        return path
    image = Image.new('RGB', (512, 512), '#fffaf0')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 500, 500), radius=32, outline='#222222', width=6, fill='#fff8e8')
    face = '#ff9778' if kind == '生气' else '#ffd75e'
    draw.ellipse((126, 50, 386, 310), fill=face, outline='#262321', width=7)
    dark = '#262321'
    if kind in ('大笑', '捂脸'):
        for x in (195, 315):
            draw.arc((x - 25, 120, x + 25, 165), 190, 350, fill=dark, width=8)
        draw.pieslice((205, 162, 310, 260), 0, 180, fill=dark)
        draw.ellipse((233, 224, 286, 246), fill='#f58e91')
    else:
        for x in (198, 310):
            draw.ellipse((x - 9, 139, x + 9, 161), fill=dark)
        if kind == '生气':
            draw.line((174, 110, 222, 130), fill=dark, width=8)
            draw.line((286, 130, 334, 110), fill=dark, width=8)
            draw.arc((214, 199, 300, 255), 185, 355, fill=dark, width=7)
        elif kind == '疑惑':
            draw.ellipse((239, 207, 267, 237), outline=dark, width=6)
            draw.line((173, 117, 217, 109), fill=dark, width=7)
        else:
            draw.arc((198, 165, 318, 250), 5, 165, fill=dark, width=8)
            if kind == '得意':
                draw.line((287, 139, 331, 144), fill=dark, width=7)
    if kind == '捂脸':
        draw.rounded_rectangle((250, 115, 370, 232), radius=35, fill='#ffd0a2', outline=dark, width=5)
    if kind == '点赞':
        draw.rounded_rectangle((330, 215, 416, 290), radius=20, fill='#ffd0a2', outline=dark, width=5)
        draw.rounded_rectangle((335, 175, 366, 257), radius=14, fill='#ffd0a2', outline=dark, width=5)
    font_file = r'C:\Windows\Fonts\msyhbd.ttc'
    lines = [caption[i:i + 8] for i in range(0, len(caption), 8)]
    font = ImageFont.truetype(font_file, 48 if len(lines) <= 2 else 40)
    for i, line in enumerate(lines[:3]):
        draw.text((256, 355 + i * 61), line, font=font, fill=dark, anchor='mm', stroke_width=1)
    image.save(path)
    return path


def prepare_reply(answer, output_dir=None):
    match = re.fullmatch(r'\s*\[\[表情包:([^|\]\n]+)\|([^\]\n]+)\]\]\s*', answer)
    if not match:
        return answer, None
    kind, caption = match.group(1).strip(), match.group(2).strip()[:16]
    if kind not in KINDS or not caption:
        return caption or '😂', None
    try:
        path = render_card(kind, caption, output_dir)
        return '[表情包：' + caption + ']', path
    except Exception as exc:
        print('表情包渲染失败，改发文字：', type(exc).__name__, flush=True)
        return caption, None
