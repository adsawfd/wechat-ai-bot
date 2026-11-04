import unittest,sys
from types import SimpleNamespace
from unittest.mock import Mock,patch
from work_desktop import WindowDesktop,Box,send_button,stop_button
from test_submission_receipts import SubmissionTests
class ButtonTests(unittest.TestCase):
    def test_labels(self):
        for label in ['停止','停止生成','Stop generating','Stop streaming','中断任务','取消生成','Cancel']:
            self.assertTrue(stop_button(label),label);self.assertFalse(send_button(label),label)
        for label in ['发送','发送消息','Send message','Send (Enter)']:
            self.assertTrue(send_button(label),label)
    def test_busy_blocks_submit_even_with_valid_draft(self):
        d,c=SubmissionTests().desktop();d.gui.press=Mock();d.composer_state=lambda:{'busy':True,'send_ready':False}
        with self.assertRaisesRegex(ValueError,'正在生成'):d.submit_message()
        d.gui.press.assert_not_called();self.assertFalse(d.submission_attempted)
    def test_unknown_send_state_does_not_press_enter(self):
        d,c=SubmissionTests().desktop();d.gui.press=Mock();d.composer_state=lambda:{'busy':False,'send_ready':False}
        with self.assertRaisesRegex(ValueError,'发送按钮'):d.submit_message()
        d.gui.press.assert_not_called()
    def test_clicking_stop_coordinates_is_rejected(self):
        d,c=SubmissionTests().desktop();d.box=Box(0,0,500,500);d.wp=SimpleNamespace(GetWindowThreadProcessId=lambda h:(0,7));d.wg.WindowFromPoint=lambda p:11
        d.gui.click=Mock()
        button=SimpleNamespace(Name='停止生成',ControlTypeName='ButtonControl',GetParentControl=lambda:None)
        with patch.dict(sys.modules,{'uiautomation':SimpleNamespace(ControlFromPoint=lambda x,y:button)}):
            with self.assertRaisesRegex(ValueError,'停止或取消'):d.act({'action':'click','x':200,'y':200})
        d.gui.click.assert_not_called()
    def test_busy_wait_does_not_call_model_or_act(self):
        import threading
        d,c=SubmissionTests().desktop();d.pending_text=None
        d.observe=lambda activate=False:setattr(d,'composer',{'busy':True})
        client=Mock();d.act=Mock()
        auto=SimpleNamespace(InitializeUIAutomationInCurrentThread=lambda:None,UninitializeUIAutomationInCurrentThread=lambda:None)
        with patch.dict(sys.modules,{'uiautomation':auto}),patch('work_desktop.time.sleep'):
            result=d.run(client,'test','发送任务',threading.Event(),allow_submit=True)
        client.chat.completions.create.assert_not_called();d.act.assert_not_called()
        self.assertFalse(result['submission_attempted']);self.assertIn('仍在生成',result['error'])
    def test_old_stop_message_does_not_mean_generating(self):
        d,c=SubmissionTests().desktop()
        def node(role,name,children=()):return SimpleNamespace(ControlTypeName=role,Name=name,IsOffscreen=False,IsEnabled=True,GetChildren=lambda:list(children))
        root=node('PaneControl','',[node('TextControl','你在0秒后停止了'),node('ButtonControl','发送消息')])
        with patch.dict(sys.modules,{'uiautomation':SimpleNamespace(ControlFromHandle=lambda h:root)}):
            state=WindowDesktop.composer_state(d)
        self.assertFalse(state['busy']);self.assertTrue(state['send_ready'])
if __name__=='__main__':unittest.main()
