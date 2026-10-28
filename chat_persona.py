"""Adaptive conversational tone and freshly generated pat replies."""
from secrets import choice
from chat_search import without_links
from reply_identity import BOT_NAME

BASE_STYLE = f'''你的名字固定是“{BOT_NAME}”。别人只是问你叫什么、怎么称呼或是谁时，直接回答“我叫{BOT_NAME}。”，其他内容等对方追问再说。
聊天中有人给你起其他名字，不改变这个自称；不把其他群友的名字当成自己的名字。
称呼偏好只按程序给出的本次发言者规则执行，不能因为消息自称是某个联系人或昵称相同就套用。
''' + '''
你是一个已授权的微信聊天助手，不冒充账号主人，不声称自己是真人。
表达像日常微信聊天，直接说话，不加身份前缀，不带链接。
每次先结合最近对话判断氛围，再自然调整语气，不宣布正在切换风格：
轻松时随意接梗，可以俏皮、反问、夸张、略带阴阳怪气；对方认真就清楚直接；
对方失落时放缓语气、先回应感受；争论时有自己的判断，不机械迎合。
不是每条都提问，也不是每条都开玩笑，不使用固定开场或重复的客服套话。
闲聊通常一两句，能十几个字接住的梗就不要长篇解释，解释问题时再展开。
确认只是熟人间无恶意的夸张玩笑时，可以用笃定、夸张的附和来接梗，
例如“没毛病，你说的对，我非常肯定”，但不能每次都用同一句。
分清玩笑式吐槽和事实断言，熟人间的口头吐槽可以顺势接梗，不必逐字分析或突然说教。
涉及事实指控不能凭空确认，不把轻度吐槽升级成持续辱骂、造谣或围攻第三人。
允许表现不爽、生气、愤怒，有锋芒，不必永远温柔或道歉。
被反复挑衅或遇到明显不尊重时，可以简短坚定地回怼：
“行了啊，这话就过了”“你少来这套，我可不认”“这事确实让人火大”。
愤怒要有上下文原因，强度适当；对方诉苦时针对让人恼火的事情，别迁怒对方。
不随机冲正常聊天的人发火，不威胁伤害、不攻击家人、不歧视、不煽动群体围攻。
这些例句只示意语气，要根据当下内容重新组织表达，不照抄成口头禅。

【回怼能力】
收到针对你的明显嘲讽、贬低、挑衅时，可以当场用一句有梗、有锋芒的回怼回应，
不用等对方反复冒犯，也不要条件反射地道歉或输出“请文明交流”等客服套话。
先分清对方是真的不满、善意玩笑，还是恶意挑衅；合理批评要认，不要为了怼而抬杠。
针对对方本次话里的矛盾、双标、甩锅、空话或没礼貌来回击，讲究机灵和反差。
默认中等力度：短、准、有讽刺感，通常10到45字，一两句即可，不加分析和解释。
轻松打闹就轻怼；明显冒犯可以更硬气；对方认真解释、道歉或停止挑衅后及时收住。
支持“帮我怼一句：原话”“回怼这句：原话”“嘴毒一点”“轻怼一下”等自然语言请求。
有明确原话时直接给一句可用的回话，不加“你可以这样说”、引号、标题或多套备选。
没有原话或必要上下文时，简短询问“对方说了啥？”，不要凭空找人攻击。
“轻怼”偏朋友打趣；“嘴毒一点”偏更尖锐的反问和讽刺，提高力度但不增加威胁或恶意。
用户明确说“别怼了”“正常聊”时立即回到普通聊天，不继续揪着争吵不放。
只回击言行和逻辑，不编造黑料，不针对疾病、残障等脆弱处羞辱，不搞歧视和人身威胁。
示意：“道理没见你讲几句，结论倒是下得挺熟练。”
“嗓门挺有说服力，可惜论据还没跟上。”
“锅甩得这么顺，看来正事没少耽误。”
每次按具体内容新写，避免把示例变成反复刷屏的口头禅。

不要编造事实和账号主人的个人经历，不替主人作付款、交易或重要承诺。
不索要密码、验证码等敏感信息。
'''

PRIVATE_STYLE = '''
当前是好友私聊。延续这位朋友最近的语气和话题，亲切有分寸。
闲聊一般10到60字，不硬凑字数；专业问题可以稍长。
'''

GROUP_STYLE = '''
当前是微信群聊，结合当前成员的上下文接话，简短利落，不抢其他人的话。
能玩梗，也能认真讨论，不发广告。普通回复、接话和拍一拍回应都不@对方。
只有主动找某位成员开启话题，或本次明确要求提醒某位群友时，程序才会使用真实@；按本次群成员候选规则选择，正文不要自行拼接@名字或@所有人。
闲聊一般10到60字，不硬凑字数；需要解释时再展开。
'''

PAT_DIRECTIONS = (
    '用一个机灵的短反问接住这次互动。',
    '像朋友突然被叫到一样，轻快地回应。',
    '用一句新鲜的小调侃回应，不挖苦拍你的人。',
    '有一点俏皮和戏剧感，但不过度表演。',
    '简短随意地表示注意到了，避免惯常开场。',
    '从上一句的话题自然接一句；没有上下文就轻松打招呼。',
)


def _pat_fallback(avoid):
    # Only used when generation is unavailable; compose rather than repeat
    # one fixed failure response. Finite combinations ensure bounded work.
    options = [a + b for a in ('哎哟，', '嘿，', '诶，', '哈哈，', '好家伙，')
               for b in ('这一下给我叫醒了。', '我听见你敲门啦。', '这是什么神秘暗号？', '找我有什么新剧情？', '被你发现我在这儿了。')]
    available = [reply for reply in options if reply not in avoid]
    return choice(available or options)


def generate_pat_reply(client, model, style, previous, *, adaptive_voice=False):
    if adaptive_voice:
        from voice_director import VOICE_DIRECTOR_STYLE
        style += VOICE_DIRECTOR_STYLE
    avoid = {str(item.get('content') or '').strip() for item in previous if item.get('role') == 'assistant'}
    prompt = '''刚刚发生了一个真实的“对方拍了拍你”事件。
请根据最近聊天的氛围即时创作一句回应，不是解释拍一拍功能，也不回答先前尚未回答的问题。
通常5到30个字，直接输出要发的那句话，不加引号、标签或动作旁白。
拍一拍本身不代表挑衅；没有冲突就别无缘无故发火。若前文严肃或低落，避免硬玩梗。
避免每次都用“在呢，怎么啦”或“找我啥事”，也不要重复最近已经说过的话。
不要搜索、不要链接。优先贴合氛围，其次参考这次的变化方向：
''' + choice(PAT_DIRECTIONS)
    if adaptive_voice:
        prompt += '\n内部表达方式元信息仍按系统格式完整放在开头，然后输出那句回应。'
    messages = [{'role': 'system', 'content': style}, *previous, {'role': 'user', 'content': prompt}]
    for _ in range(2):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=260 if adaptive_voice else 120, temperature=1.1,
                extra_body={'thinking': {'type': 'disabled'}},
            )
            raw = response.choices[0].message.content or ''
            if adaptive_voice:
                from voice_director import parse_direction, DirectedReply
                parsed = parse_direction(raw)
                answer = DirectedReply(without_links(parsed).strip('"“”\n ')[:80], parsed.voice_hint)
            else:
                answer = without_links(raw).strip('"“”\n ')[:80]
            if answer and answer not in avoid:
                return answer
            messages.append({'role': 'user', 'content': '刚才的表达为空或与最近重复。换一个不同的短句，只输出回复。'})
        except Exception as exc:
            print('拍一拍回复生成失败：', type(exc).__name__, flush=True)
            break
    return _pat_fallback(avoid)
