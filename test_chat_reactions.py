import unittest
from unittest.mock import Mock
from chat_reactions import is_reaction_text
from group_engagement import GroupEngagement


class ReactionTests(unittest.TestCase):
    def test_wechat_codes_and_unicode_emoji_are_reactions_not_media_placeholders(self):
        for text in ('[脸红]','[捂脸][偷笑]','😳','😂','👨‍👩‍👧','👍🏽',' ❤️ '):
            self.assertTrue(is_reaction_text(text),text)
        for text in ('','普通文字','我笑了😂','[图片]','[文件]','[链接]','?','\ufe0f'):
            self.assertFalse(is_reaction_text(text),text)

    def test_single_emoji_reaches_context_judgment_only_after_account_has_spoken(self):
        classifier=Mock(return_value={'kind':'directed','confidence':0.65})
        g=GroupEngagement(classifier=classifier)
        g.observe('room','a','😳',1)
        self.assertIsNone(g.decide(None,'model','room','a','😳'))
        classifier.assert_not_called()
        g.record_self_message('room','夸得我都飘了',2)
        g.observe('room','a','😳',3)
        self.assertEqual(g.decide(None,'model','room','a','😳'),'context')
        classifier.assert_called_once()

    def test_lower_reaction_threshold_requires_immediately_preceding_bot_message(self):
        classifier=Mock(return_value={'kind':'directed','confidence':0.65})
        g=GroupEngagement(classifier=classifier)
        g.record_self_message('room','先前的一句',1)
        g.observe('room','a','在跟其他群友说事',2)
        g.observe('room','b','[脸红]',3)
        self.assertIsNone(g.decide(None,'model','room','b','[脸红]'))
        g.record_self_message('room','新的一句',4)
        g.observe('room','b','[脸红]',5)
        classifier.return_value={'kind':'directed','confidence':0.3}
        self.assertIsNone(g.decide(None,'model','room','b','[脸红]'))

    def test_self_event_deduplicates_program_send_and_never_extends_its_own_loop(self):
        g=GroupEngagement()
        g.record_reply('room','一句正常回复')
        g.record_self_message('room','一句正常回复',1)
        g.record_self_message('room','一句正常回复',1)
        self.assertEqual(len(g.rooms['room']['messages']),1)
        g.record_self_message('room','随后手动发的一句',2)
        self.assertEqual(len(g.rooms['room']['messages']),2)
        self.assertIn('随后手动发的一句',g.context_note('room'))


if __name__=='__main__':
    unittest.main()
