import os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import redirect_stdout
from io import StringIO
from test_group_followups import FollowupTests
from work_assistant import WorkAssistant
class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.f=FollowupTests();self.f.setUp()
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.a=WorkAssistant(None,'test',{'owner1','owner2'},True,root=Path(self.temp.name))
        self.a.submit=Mock(return_value='started')
        self.f.scope['remote_computer']=self.a
    def deliver(self,text,sender='owner1',age=0):
        m=self.f.text_type();m.content=text;m.attr='friend';m.sender_wxid=sender;m.sender=sender
        m.local_id=9;m.sort_seq=10;m.create_time=int(time.time())-age
        chat=SimpleNamespace(who=sender,nickname='测试联系人',SendMsg=Mock(return_value=True))
        with redirect_stdout(StringIO()):self.f.scope['on_message'](m,chat)
    def test_authorized_private_task(self):
        self.deliver('电脑操作:生成一份Word')
        self.a.submit.assert_called_once();self.f.generate.assert_not_called()
    def test_screenshot_request_enters_worker(self):
        self.deliver('你帮我在桌面新建一个文本文本，然后在里面输入微信助手，你好然后把这个文件发给我')
        self.a.submit.assert_called_once();self.f.generate.assert_not_called()
    def test_latest_greeting_request_enters_worker(self):
        self.deliver('微信助手，你好，帮我在桌面创建一个文本文件，然后在里面输入微信助手，你好并保存，然后把这个文件回传给我')
        self.a.submit.assert_called_once();self.f.generate.assert_not_called()
    def test_unauthorized_never_runs_task(self):
        self.deliver('电脑操作:生成一份Word',sender='outsider')
        self.a.submit.assert_not_called()
    def test_stale_command_not_executed(self):
        self.deliver('电脑操作:生成一份Word',age=120)
        self.a.submit.assert_not_called();self.f.generate.assert_not_called()
    def test_followup_reuses_task_routing(self):
        self.a.session('owner1')
        self.deliver('把刚才那个文件加一段总结')
        self.a.submit.assert_called_once();self.f.generate.assert_not_called()
if __name__=='__main__':unittest.main()
