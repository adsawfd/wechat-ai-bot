import tempfile,unittest
from pathlib import Path
from group_silence import GroupSilence,control_intent
class SilenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'silence.sqlite3'
        self.s=GroupSilence('me',{'boss1','boss2'},self.path)
        self.room='room@chatroom'
    def test_phrases(self):
        for text in ['闭嘴','你闭嘴！','微信助手，闭嘴','不要再讲话','别再说话了','请你不要回复了','安静点','停止发言','@大肥鱼1.0\u2005闭嘴']:
            self.assertEqual(control_intent(text,['大肥鱼1.0']),'mute',text)
        for text in ['他说闭嘴','闭嘴是什么意思','如果我说闭嘴','请不要闭嘴','@成员乙 闭嘴','“闭嘴”','你为什么不说话了']:
            self.assertIsNone(control_intent(text),text)
        for text in ['可以说话了','恢复说话','微信助手，恢复自动回复','解除静音']:
            self.assertEqual(control_intent(text),'resume',text)
    def test_permissions_persistence_and_one_ack(self):
        self.assertIsNone(self.s.control(self.room,'outsider','闭嘴',1))
        self.assertIsNone(self.s.control(self.room,'boss1','闭嘴',1,quoted=True))
        self.assertTrue(self.s.control(self.room,'boss1','闭嘴',1)['ack'])
        self.assertFalse(self.s.control(self.room,'boss2','闭嘴',2)['ack'])
        self.assertTrue(GroupSilence('me',{'boss1'},self.path).muted(self.room))
        self.assertFalse(self.s.muted('other@chatroom'))
        self.assertFalse(GroupSilence('other-account',{'boss1'},self.path).muted(self.room))
        self.assertIsNone(self.s.control(self.room,'outsider','恢复说话',3))
        self.assertTrue(self.s.muted(self.room))
        self.assertTrue(self.s.control(self.room,'boss2','恢复说话',3)['ack'])
        self.assertFalse(self.s.muted(self.room))
        self.assertFalse(self.s.control(self.room,'boss1','闭嘴',1)['ack'])
        self.assertFalse(self.s.muted(self.room))
    def test_old_inflight_reply_is_dropped_even_after_resume(self):
        token=self.s.token(self.room)
        self.s.control(self.room,'boss1','闭嘴',1)
        with self.s.delivery(self.room,token) as allowed:self.assertFalse(allowed)
        self.s.control(self.room,'boss1','恢复说话',2)
        with self.s.delivery(self.room,token) as allowed:self.assertFalse(allowed)
        with self.s.delivery(self.room,self.s.token(self.room)) as allowed:self.assertTrue(allowed)
if __name__=='__main__':unittest.main()
