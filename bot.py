
import os
import html
import re
from collections import defaultdict, deque
from threading import Lock

from dotenv import load_dotenv
from openai import OpenAI
from chat_search import generate_answer
from chat_persona import BASE_STYLE, PRIVATE_STYLE, GROUP_STYLE, generate_pat_reply
from pat_events import get_pat_sender
from group_mentions import send_group_reply, send_image_reply, send_group_mention
from mention_planner import build_mention_roster, strip_mention_control, has_mention_request
from bot_runtime import configure_runtime, attach_gui
from bot_account import open_bound_database
from reply_media import prepare_reply, MEDIA_STYLE
from sticker_battle import generate_sticker_reply
from nickname_trigger import NicknameTrigger
from incoming_context import IncomingImages, read_quote, quote_context
from incoming_video import IncomingVideos
from native_video import ensure_video_cached
from group_engagement import GroupEngagement, delivery_succeeded
from proactive_pats import ProactivePats, PAT_STYLE, extract_pat_intent
from native_pat import send_native_pat
from reply_identity import ReplyIdentity
from voice_audio import spoken_text
from voice_director import VoiceDirector
from singing import singing_available, singing_note, send_singing_reply
from native_voice import send_native_voice, recover_voice_audio
from wechatauto import WeChat
from wechatauto.msgs import FriendTextMessage
from wechatauto.msgs.friend import FriendEmojiMessage, FriendImageMessage, FriendQuoteMessage, FriendVideoMessage

load_dotenv()
configure_runtime()

# ===== 基础配置 =====
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
MODEL = os.getenv("AI_MODEL", "deepseek-flash")
AUTO_SEND = os.getenv("ENABLE_SEND", "0") == "1"
VISION_UPLOAD = os.getenv("ENABLE_VISION_UPLOAD", "0") == "1"
VOICE_ENABLED = os.getenv("ENABLE_NATIVE_VOICE", "1") == "1"

PRIVATE_MODE = os.getenv("PRIVATE_MODE", "test")
TEST_FRIEND = os.getenv("WECHAT_TEST_CONTACT", "").strip()
GROUPS = {
    name.strip()
    for name in os.getenv("GROUP_NAMES", "").split(",")
    if name.strip()
}
TRIGGER = os.getenv("GROUP_TRIGGER", "/ai").strip()

if not API_KEY:
    raise RuntimeError("请在 .env 填写 DeepSeek API Key")

if PRIVATE_MODE not in ("test", "all"):
    raise RuntimeError("PRIVATE_MODE 只能是 test 或 all")

if PRIVATE_MODE == "test" and not TEST_FRIEND:
    raise RuntimeError("请填写测试好友备注名")


# ===== DeepSeek =====
ai = OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com",
    timeout=30.0,
    max_retries=0
)

# ===== 微信连接 =====
wx = WeChat(db=open_bound_database())
attach_gui(wx._gui)
self_id = wx._db.get_self_info().get("username")

if not self_id:
    raise RuntimeError("无法确认当前微信账号身份")

nickname_trigger = NicknameTrigger(wx._db, self_id)
incoming_images = IncomingImages(wx._db)
incoming_videos = IncomingVideos(wx._db, opener=ensure_video_cached)
recover_voice_audio()

# ===== 聊天记忆 =====
histories = defaultdict(lambda: deque(maxlen=8))
seen = set()
seen_order = deque()
lock = Lock()
# 每个群成员独立进入接话状态；/结束 或重启后退出。
group_followups = {}
group_engagement = GroupEngagement()
proactive_pats = ProactivePats(enabled=os.getenv('ENABLE_PROACTIVE_PAT', '1') == '1')
voice_director = VoiceDirector(gender=os.getenv('VOICE_GENDER', 'male'))
reply_identity = ReplyIdentity.load(self_id)


# 聊天风格与拍一拍动态回复在 chat_persona.py 中统一配置。

# ===== 通过微信原始元数据识别真实 @ =====
def get_at_user_ids(msg, chat):
    """
    从消息数据库的 source 字段读取 @ 用户列表。
    无法确认时返回 None，绝不按普通文字猜测。
    """
    chat_id = str(getattr(chat, "who", "") or "")
    local_id = getattr(msg, "local_id", None)
    sort_seq = getattr(msg, "sort_seq", None)

    if not chat_id.endswith("@chatroom"):
        return None

    if local_id is None or sort_seq is None:
        return None

    try:
        # Read the exact native row for text, image and composite quote types.
        rows = wx._db.get_message_rows_for_media(chat_id, int(local_id))
        matches = [row for row in rows if str(row.get("sort_seq")) == str(sort_seq)]

        # 不允许猜测消息所在分片
        if len(matches) != 1:
            print("无法唯一定位群消息，跳过", flush=True)
            return None

        raw = matches[0]

        if not raw:
            return None

        if str(raw.get("sort_seq")) != str(sort_seq):
            return None

        source = raw.get("source") or ""

        if isinstance(source, memoryview):
            source = source.tobytes()

        if isinstance(source, bytes):
            # 微信 4.x 的 source 可能是 Zstandard 帧，须先解压再解析 XML。
            if source.startswith(b"\x28\xb5\x2f\xfd"):
                from wechatauto.db import _get_zstd_module, _zstd_decompress
                zstd = _get_zstd_module()
                if zstd is None:
                    print("缺少 Zstandard 解压模块，跳过群消息", flush=True)
                    return None
                source = _zstd_decompress(zstd, source)
                if source is None:
                    print("群消息 source 解压失败，跳过", flush=True)
                    return None
            else:
                source = source.decode("utf-8")
        else:
            source = str(source)

        source = html.unescape(source)

        # 只从真正的 atuserlist XML 字段读取
        
        match = re.search(
            r"<atuserlist[^>]*>(.*?)</atuserlist>",
            source,
            flags=re.IGNORECASE | re.DOTALL
        )

        
        if not match:
            # 已定位到消息；有 source 但无 @ 列表即普通群消息。
            # 元数据缺失仍视为未知，避免误接话。
            native_type = int(raw.get("local_type") or 0) & 0xffffffff
            return set() if source.strip() or native_type in (3, 49) else None

        value = match.group(1).strip()

        value = re.sub(
            r"<!\[CDATA\[(.*?)\]\]>",
            r"\1",
            value,
            flags=re.DOTALL
        )

        return {
            item.strip()
            for item in re.split(r"[,;\s]+", value)
            if item.strip()
        }


    except Exception as e:
        print(
            "真实@识别失败：",
            type(e).__name__,
            flush=True
        )
        return None


def is_really_at_me(msg, chat):
    at_ids = get_at_user_ids(msg, chat)

    if at_ids is None:
        return False

    # 排除 @所有人
    if "notify@all" in at_ids:
        return False

    # 必须是当前微信账号的真实 wxid
    return self_id in at_ids


# ===== 接收消息 =====
def on_message(msg, chat):
    # AddListenAll also reports our own sends, including messages entered in the
    # WeChat UI. Remember them as context, then stop; never reply to ourselves.
    if getattr(msg, 'attr', '') == 'self' and getattr(msg, 'sender_wxid', '') == self_id:
        own_chat_id = str(getattr(chat, 'who', '') or '')
        own_chat_name = str(getattr(chat, 'nickname', own_chat_id) or own_chat_id)
        own_content = str(getattr(msg, 'content', '') or '').strip()
        own_seq, own_local = getattr(msg, 'sort_seq', None), getattr(msg, 'local_id', None)
        if (own_chat_id.endswith('@chatroom') and (not GROUPS or own_chat_name in GROUPS)
                and getattr(msg, 'type', '') == 'text' and 0 < len(own_content) <= 1000
                and (own_seq is not None or own_local is not None)
                and not any(word in own_content for word in ('验证码', '登录密码', '银行卡密码', '收款码', '转账', '汇款'))):
            group_engagement.record_self_message(own_chat_id, own_content, (own_seq, own_local))
        return
    # 拍一拍是原生事件卡片，需要在文字过滤之前单独识别。
    is_emoji = isinstance(msg, FriendEmojiMessage)
    is_image = isinstance(msg, FriendImageMessage)
    is_video = isinstance(msg, FriendVideoMessage)
    known_content = isinstance(msg, (FriendTextMessage, FriendEmojiMessage, FriendImageMessage, FriendVideoMessage))
    quote = read_quote(msg, chat, wx._db) if not known_content else None
    is_quote = isinstance(msg, FriendQuoteMessage) or quote is not None
    if is_quote and quote is None:
        print("未能读取引用原文，跳过本次消息", flush=True)
        return
    is_pat = not known_content and not is_quote
    if is_pat:
        sender_id = get_pat_sender(msg, chat, wx._db, self_id)
        if not sender_id:
            return
    else:
        if getattr(msg, "attr", "") != "friend":
            return
        sender_id = str(getattr(msg, "sender_wxid", "") or "").strip()

    # 防止回复自己的消息
    if sender_id == self_id:
        return

    chat_id = str(getattr(chat, "who", "") or "")
    chat_name = str(
        getattr(chat, "nickname", chat_id) or chat_id
    )
    is_group = chat_id.endswith("@chatroom")

    # 跳过文件传输助手和公众号
    if chat_id == "filehelper" or chat_id.startswith("gh_"):
        return

    if is_pat:
        content = "对方刚刚拍了拍你。"
    elif is_image:
        content = "请结合前文查看这张图片，自然回应；需要识字、说明或分析时按对方的问题回答。"
    elif is_video:
        content = "请结合前文理解这段视频的关键画面、字幕和实际识别到的对白，自然接话；没有读取到的部分不能猜测。"
    elif is_quote:
        content = quote["question"] or "请结合被引用的原文回应。"
    elif is_emoji:
        content = "对方发来了一个表情包。请先理解附图的文字、表情和动作，再结合前文接话回图。"
    else:
        content = str(getattr(msg, "content", "") or "")

    if is_group:
        # 解析部分群消息正文前的 wxid 前缀
        content = re.sub(
            r"^wxid_[A-Za-z0-9_]+:\s*\n",
            "",
            content,
            count=1
        )

    content = content.strip()

    if not content or len(content) > 1000:
        return

    blocked = ("验证码", "登录密码", "银行卡密码", "收款码", "转账", "汇款")
    if any(word in content for word in blocked):
        print("跳过敏感消息", flush=True)
        return

    seq = getattr(msg, "sort_seq", None)
    local_id = getattr(msg, "local_id", None)
    if seq is None and local_id is None:
        print("缺少消息编号，安全跳过", flush=True)
        return
    message_key = (chat_id, seq, local_id)
    boss_ack_hint = (not (is_pat or is_image or is_video or is_emoji)
                     and reply_identity.is_boss(sender_id) and reply_identity.explicit_request(content))
    with lock:
        if message_key in seen:
            return


    direct_at_me = False
    called_by_name = False
    engagement_mode = None
    mention_roster = None
    history_key = (chat_id, sender_id) if is_group else chat_id

    # ===== 场景识别 =====
    
    
    if is_group:
        # GROUPS 留空时允许所有微信群
        if GROUPS and chat_name not in GROUPS:
            return

        # 无法确认群成员身份时跳过
        if not sender_id or sender_id.isdigit():
            return
        proactive_pats.observe_preferences(chat_id, sender_id, content)

        if is_image or is_emoji:
            incoming_videos.forget(chat_id, sender_id)
            incoming_images.remember(msg, chat_id, sender_id)
        elif is_video:
            incoming_images.forget(chat_id, sender_id)
            incoming_videos.remember(msg, chat_id, sender_id)

        if not is_pat:
            called_by_name = not (is_emoji or is_image or is_video) and nickname_trigger.matches(content)
            at_ids = set() if is_emoji or is_image or is_video else get_at_user_ids(msg, chat)
            if at_ids is None or "notify@all" in at_ids:
                return
            direct_at_me = self_id in at_ids
            observed_text = '[表情包]' if is_emoji else ('[图片]' if is_image else ('[视频]' if is_video else content))
            group_engagement.recover_context(wx._db, chat_id, msg, self_id)
            if not group_engagement.observe(chat_id, sender_id, observed_text, message_key,
                                            addressed_to_others=bool(at_ids and not direct_at_me)):
                return
            proactive_pats.observe(chat_id, sender_id, content, message_key)
            with lock:
                continuing = history_key in group_followups
            # An explicit request for the bot to call somebody is distinct from
            # two other members talking to one another.
            invitation = ((called_by_name and has_mention_request(content)) or
                          (continuing and has_mention_request(content,addressed=True)))
            if at_ids and not direct_at_me and not invitation:
                return
            quoting_me = bool(quote and quote.get("sender_id") == self_id)
            if content in ("/结束", "/停止接话"):
                with lock:
                    group_followups.pop(history_key, None)
                    histories.pop(history_key, None)
                group_engagement.pause(chat_id, sender_id)
                print("已停止这位群成员的接话，重新 @ 或叫昵称可恢复", flush=True)
                if reply_identity.is_boss(sender_id) and AUTO_SEND:
                    print('停止接话回应：',send_group_reply(chat,'好的老板，已停止接话。',sender_id,wx._db),flush=True)
                return
            if direct_at_me or called_by_name or quoting_me:
                group_engagement.resume(chat_id, sender_id)
            if not direct_at_me and not called_by_name and not quoting_me and not continuing and not is_emoji:
                if is_image or is_video:
                    return
                identity_hint = nickname_trigger.reference_hint(content)
                engagement_mode = group_engagement.decide(ai, MODEL, chat_id, sender_id, content, identity=identity_hint, quoted=is_quote,
                    allow_pat=proactive_pats.can_consider(chat_id, sender_id, content, message_key))
                if not engagement_mode:
                    return
                if engagement_mode == 'ambient_pat':
                    # A light interaction can stand on its own: no generated
                    # text, new followup session, or fake assistant message.
                    with lock:
                        if message_key in seen:
                            return
                        seen.add(message_key)
                        seen_order.append(message_key)
                        if len(seen_order) > 2000:
                            seen.discard(seen_order.popleft())
                    if not AUTO_SEND:
                        print('群聊氛围适合拍一拍，预览模式未执行', flush=True)
                    elif proactive_pats.choose(chat_id, sender_id, content, message_key, suggested=True):
                        if boss_ack_hint:
                            ack_result=send_group_reply(chat,'好的老板',sender_id,wx._db)
                            print('指令回应：',ack_result,flush=True)
                            if not delivery_succeeded(ack_result):
                                return
                        print('根据群聊氛围主动拍一拍：', chat_name, flush=True)
                        pat_result = send_native_pat(chat, msg, sender_id, wx._db, self_id)
                        print('主动拍一拍结果：', pat_result, flush=True)
                        if delivery_succeeded(pat_result):
                            group_engagement.record_pat(chat_id, sender_id)
                    return

        question = content.strip()

        if not question:
            return

        style = BASE_STYLE + GROUP_STYLE + MEDIA_STYLE

        sender = str(
            getattr(msg, "sender", "") or sender_id
        )

        user_text = "一位群成员刚刚拍了拍你。" if is_pat else f"群成员 {sender} 提问：{question}"
        user_text += group_engagement.context_note(chat_id)
        if engagement_mode:
            print('群聊接话方式：', engagement_mode, flush=True)
            style += ('\n对方虽然没有@你，但正在接你的话或谈论你；结合群上下文直接回应。' if engagement_mode in ('context', 'mentioned')
                      else '\n这次是适时参与群友的开放提问或吐槽。简短接一句，有帮助或有共鸣即可；不要抢话。只有有明确上下文理由邀请相关成员加入，才按群成员规则选择真实@。')

        print(
            "检测到有人拍了拍我：" if is_pat else ("检测到真实@我的群消息：" if direct_at_me else ("检测到当前微信昵称：" if called_by_name else "接续群成员对话：")),
            chat_name,
            flush=True
        )

    else:
        # 默认仅自动回复测试好友
        if PRIVATE_MODE == "test":
            if chat_name != TEST_FRIEND:
                return
        proactive_pats.observe_preferences(chat_id, sender_id, content)

        if is_image or is_emoji:
            incoming_videos.forget(chat_id, sender_id)
            incoming_images.remember(msg, chat_id, sender_id)
        elif is_video:
            incoming_images.forget(chat_id, sender_id)
            incoming_videos.remember(msg, chat_id, sender_id)

        question = content
        style = BASE_STYLE + PRIVATE_STYLE + MEDIA_STYLE
        user_text = question

    # ===== 防重复、限流 =====

    with lock:
        if message_key in seen:
            return

        seen.add(message_key)
        seen_order.append(message_key)

        if len(seen_order) > 2000:
            seen.discard(seen_order.popleft())

        if is_group and not is_pat and not is_emoji and not engagement_mode:
            group_followups.pop(history_key, None)
            group_followups[history_key] = None
            # 限制长期运行的会话状态数量，不加入消息冷却。
            if len(group_followups) > 2000:
                oldest = next(iter(group_followups))
                group_followups.pop(oldest, None)
                histories.pop(oldest, None)
        previous = list(histories[history_key])

    print(
        f"收到{'群聊' if is_group else '私聊'}消息："
        f"{chat_name}",
        flush=True
    )

    # ===== AI 生成回复 =====
    try:
        if is_group and not is_pat:
            mention_roster = build_mention_roster(wx._db,chat_id,sender_id,self_id,content,at_ids=at_ids,
                recent_ids=group_engagement.recent_member_ids(chat_id),
                allow_openers=not (is_quote or is_emoji or is_image or is_video))
            if mention_roster is not None:
                style += mention_roster.note()
        if not is_pat:
            style += reply_identity.style_for(sender_id)
        if VOICE_ENABLED and not is_emoji:
            style += voice_director.note(history_key)
            style += singing_note()
        if not is_pat:
            style += PAT_STYLE
        if is_pat:
            answer = generate_pat_reply(ai, MODEL, style, previous, adaptive_voice=VOICE_ENABLED)
        else:
            user_text += quote_context(quote)
            video_context = incoming_videos.for_message(msg, chat_id, sender_id, quote=quote,
                                                        is_video=is_video, allow_frames=VISION_UPLOAD, chat=chat)
            if video_context is not None:
                image_blocks, image_note = video_context.blocks, video_context.note
            else:
                image_blocks, image_note = incoming_images.for_message(msg, chat_id, sender_id, quote=quote, is_image=is_image, is_sticker=is_emoji)
            if image_blocks and not VISION_UPLOAD:
                if is_image or is_emoji or (quote and quote.get('reference_type') in ('3', '47')):
                    print('已在本机读取画面；图片外发给DeepSeek尚未确认，跳过视觉调用和本次回复', flush=True)
                    return
                image_blocks = []
                image_note = '图片理解当前未开启，模型未取得画面；若本次追问与图片有关如实说明，其他话题正常回应。'
            if image_note:
                user_text += "\n" + image_note
            if image_blocks:
                print("已读取视频关键画面，结合对白分析" if video_context is not None else "已读取图片，发送给视觉模型分析", flush=True)
                if is_emoji:
                    answer = generate_sticker_reply(ai, MODEL, style, previous, user_text, images=image_blocks)
                    if not answer:
                        print('表情含义或回图未生成有效结果，本次跳过', flush=True)
                        return
                else:
                    answer = generate_answer(ai, MODEL, style, previous, user_text, images=image_blocks, adaptive_voice=VOICE_ENABLED)
            else:
                answer = generate_answer(ai, MODEL, style, previous, user_text, adaptive_voice=VOICE_ENABLED)

        if not answer:
            return
        voice_hint = getattr(answer, 'voice_hint', None)
        web_image_path=getattr(answer,'web_image_path',None)
        answer, pat_suggested = extract_pat_intent(answer)
        answer, boss_ack = reply_identity.prepare(answer,sender_id,requested=boss_ack_hint)
        mention_plan,mention_error = None,''
        if mention_roster is not None:
            answer,mention_plan,mention_error=mention_roster.parse(answer)
        else:
            answer=strip_mention_control(answer)
        if mention_error:
            answer,voice_hint,pat_suggested=mention_error,None,False
            web_image_path=None
        if not answer and boss_ack:
            answer = '好的老板'
        if not answer:
            return
        answer, image_path = prepare_reply(answer[:280])
        if web_image_path:
            image_path=web_image_path
        voice_plan = voice_director.choose(history_key, content, answer, voice_hint,
                                           enabled=VOICE_ENABLED, media=is_emoji or image_path is not None,
                                           singing_ready=singing_available())
        singing_requested = voice_plan.mode == 'sing'
        if voice_hint and voice_hint.get('request') == 'sing' and not singing_available():
            answer, image_path = '唱歌功能还没接通，我现在只能说话，不能真唱。', None
        voice_requested = voice_plan.mode == 'voice'
        if voice_requested:
            answer, image_path = spoken_text(answer), None
        if boss_ack and not image_path and not singing_requested and not (mention_plan and voice_requested):
            answer = reply_identity.acknowledge(answer)
        reply = answer

        print('表达方式：', '歌声原生语音' if singing_requested else ('原生语音' if voice_requested else '文字/图片'), '语气：', voice_plan.tone, flush=True)
        print("AI生成回复：", reply, flush=True)

        # ===== 自动发送 =====
        if AUTO_SEND:
            # 只尝试一次，不自动重发
            mention_media=bool(mention_plan and (voice_requested or singing_requested or image_path))
            if mention_plan and not group_engagement.reserve_mention(chat_id,message_key,requested=mention_plan.mode=='requested'):
                mention_plan,mention_media=None,False
            if mention_plan and mention_media:
                intro=reply_identity.acknowledge(mention_plan.intro) if boss_ack else mention_plan.intro
                mention_result=send_group_mention(chat,intro,mention_plan.target_id,wx._db)
                print('群聊@开场：',mention_result,flush=True)
                if not delivery_succeeded(mention_result):
                    return
                group_engagement.record_reply(chat_id,f'[向{mention_plan.target_name}发出@] '+intro)
            if boss_ack and (singing_requested or image_path) and not mention_media:
                # Media stays valid; acknowledge once before the requested
                # image/song rather than inserting words into its control data.
                ack_result=(send_group_reply(chat,'好的老板',sender_id,wx._db) if is_group else chat.SendMsg('好的老板'))
                print('指令回应：',ack_result,flush=True)
                if not delivery_succeeded(ack_result):
                    return
            if singing_requested:
                result = send_singing_reply(chat, voice_plan.song, wx._db, self_id, profile=voice_plan.profile)
                if result.get('status') == '未生成':
                    # Generation failed before any native recording attempt. A
                    # short notice is safe; never read the lyrics as a fallback.
                    reply = answer = '这次没唱出来，换一首或者等会儿再试吧。'
                    result = send_group_reply(chat, reply, sender_id, wx._db) if is_group else chat.SendMsg(reply)
                    from voice_director import VoicePlan
                    voice_plan = VoicePlan(mode='text', gender=voice_plan.gender)
            elif voice_requested:
                result = (send_native_voice(chat, reply, wx._db, self_id, profile=voice_plan.profile) if VOICE_ENABLED
                          else {'status': '失败', 'message': '原生语音发送已关闭，未改发音频文件', 'data': None})
            elif image_path:
                result = send_image_reply(chat, image_path)
            elif mention_plan and not mention_media:
                result = send_group_mention(chat,reply,mention_plan.target_id,wx._db)
            else:
                result = send_group_reply(chat, reply, sender_id, wx._db) if is_group else chat.SendMsg(reply)
            print(
                "微信发送操作返回：",
                result,
                flush=True
            )
            print(
                "请核对微信中的实际发送结果",
                flush=True
            )
            if is_group and delivery_succeeded(result):
                context_answer=(f'[向{mention_plan.target_name}发出@] '+answer if mention_plan and not mention_media else answer)
                group_engagement.record_reply(chat_id, context_answer)
            if delivery_succeeded(result):
                voice_director.record(history_key, voice_plan)
            if not mention_plan and not voice_requested and not singing_requested and delivery_succeeded(result) and proactive_pats.choose(chat_id, sender_id, content, message_key,
                                                                    suggested=pat_suggested, received_pat=is_pat):
                pat_result = send_native_pat(chat, msg, sender_id, wx._db, self_id)
                print('主动拍一拍结果：', pat_result, flush=True)
                if is_group and delivery_succeeded(pat_result):
                    group_engagement.record_pat(chat_id, sender_id)
        else:
            print(
                "预览模式：未发送",
                flush=True
            )

        # 不同私聊、群和群成员分别保存记忆
        with lock:
            histories[history_key].append({
                "role": "user",
                "content": user_text
            })
            histories[history_key].append({
                "role": "assistant",
                "content": answer
            })

    except Exception as e:
        print(
            "处理失败，不自动重发：",
            str(e),
            flush=True
        )


# ===== 启动全局监听 =====
result = wx.AddListenAll(on_message)

if not result:
    raise RuntimeError(f"全局监听失败：{result}")

print("========================", flush=True)
print("微信 AI 智能助手已启动", flush=True)
print("联网搜索：按需开启，回复不含链接", flush=True)
print("图片搜索：按请求搜索真实公开图片，取得并检查文件后发送图片",flush=True)
print("聊天风格：随对话氛围变化；支持emoji与静态表情包", flush=True)
print("内容理解：支持图片、原生表情包、引用内容；表情包先理解含义再回图", flush=True)
print("视频理解：抽取关键画面、识别字幕和本机转写前90秒对白；缺少文件时尝试打开对应视频下载", flush=True)
print("图片发送给DeepSeek：", "已允许" if VISION_UPLOAD else "等待用户确认，当前仅本机解码", flush=True)
print("斗图：收到别人表情包可自动回图，继续来图继续接；不响应自己的图", flush=True)
print("发送冷却：关闭；监听间隔：0.35秒；不最小化其他窗口", flush=True)
print("拍一拍回复：按上下文即时生成", flush=True)
print("原生语音：", "随上下文自然选择；微软自然音色，语气随聊天氛围变化" if VOICE_ENABLED else "关闭", flush=True)
print("唱歌：", "豆包O2.0曲库点歌/即兴短句；歌声标签或本机旋律检测通过后发送" if singing_available() else "等待配置唱歌服务密钥，当前不能真唱", flush=True)
print("主动拍一拍：", "结合群聊氛围偶尔主动拍，可单独拍而不发文字；支持别拍我，不自动互拍" if proactive_pats.enabled else "关闭", flush=True)
print("群聊接话：@ 或叫当前微信昵称后持续接话；/结束 退出", flush=True)
print("群聊参与：开放提问或吐槽时偶尔接话；其他成员明显在接机器人话时也会回复", flush=True)
print("昵称自动跟随微信改名，收到群消息时每10秒刷新", flush=True)
print("群聊@：可选择本群成员；明确要求提醒或自然邀请开话题时使用真实@，普通回复不@", flush=True)
print("一分钟无人接话：已关闭，不因无人回复主动发言", flush=True)
print("私聊模式：", PRIVATE_MODE, flush=True)
print("允许的群聊：", GROUPS, flush=True)
print(
    "自动发送：",
    "开启" if AUTO_SEND else "关闭",
    flush=True
)
print("按 Ctrl+C 停止机器人", flush=True)
print("========================", flush=True)

wx.KeepRunning()
