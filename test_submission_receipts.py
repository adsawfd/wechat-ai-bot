import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock,patch
from work_desktop import WindowDesktop,new_message_seen,message_text
from work_assistant import verified_screen_summary,chat_submit_requested
class SubmissionTests(unittest.TestCase):
    def desktop(self):
        d=WindowDesktop.__new__(WindowDesktop)
        d.chat_mode=True;d.allow_submit=True;d.pending_text='测试任务';d.submission_attempted=False;d.submission_verified=False
        d.composer_state=lambda:{'busy':False,'send_ready':True}
        d.info={'pid':7};d.foreground=11;d.identity=lambda:7;d.guard=lambda:None
        d.wg=SimpleNamespace(GetForegroundWindow=lambda:11)
        control=SimpleNamespace(value='测试任务',BoundingRectangle=SimpleNamespace(left=100,top=500,right=600,bottom=600))
        d.focused_editor=lambda replace=False:(control,(1,2),control.value)
        d.read_value=lambda c:(c.value,'GetValuePattern')
        d.gui=SimpleNamespace(press=lambda key:setattr(control,'value',''))
        return d,control
    def test_empty_input_alone_does_not_confirm(self):
        d,c=self.desktop();d.transcript=lambda:Counter()
        with patch('work_desktop.time.sleep'):r=d.submit_message()
        self.assertEqual(c.value,'');self.assertTrue(r['submission_attempted']);self.assertFalse(r['submission_verified'])
        self.assertEqual(d.outcome('模型说已经发送')['status'],'unverified')
        with self.assertRaises(ValueError):d.submit_message()
    def test_verified_new_transcript_message(self):
        d,c=self.desktop();before=Counter();after=Counter({message_text('测试任务'):1})
        d.transcript=Mock(side_effect=[before,after])
        with patch('work_desktop.time.sleep'):r=d.submit_message()
        self.assertTrue(r['submission_verified']);self.assertEqual(d.outcome('')['status'],'submitted')
    def test_no_verified_draft_does_not_press_enter(self):
        d,c=self.desktop();d.pending_text=None;d.gui.press=Mock()
        with self.assertRaises(ValueError):d.submit_message()
        d.gui.press.assert_not_called()
    def test_input_only_permission_cannot_submit(self):
        d,c=self.desktop();d.allow_submit=False;d.gui.press=Mock()
        with self.assertRaises(ValueError):d.submit_message()
        d.gui.press.assert_not_called()
    def test_old_duplicate_text_is_not_new_evidence(self):
        key=message_text('测试任务');before=Counter({key:1})
        self.assertFalse(new_message_seen('测试任务',before,Counter({key:1})))
        self.assertTrue(new_message_seen('测试任务',before,Counter({key:2})))
    def test_outer_model_cannot_turn_unverified_into_sent(self):
        receipts=[{'chat_mode':True,'submission_attempted':False,'submission_verified':False,'input_verified':False}]
        result=verified_screen_summary('已经输入并发送成功',receipts,'输入并发送这条任务')
        self.assertIn('未完成发送',result)
        receipts[0]['submission_attempted']=True
        self.assertIn('发送结果未确认',verified_screen_summary('已经发送',receipts,'输入并发送'))
        receipts[0]['submission_verified']=True
        self.assertIn('不代表对方已完成',verified_screen_summary('定时任务已设置成功',receipts,'发送任务'))
    def test_no_tool_execution_cannot_claim_sent(self):
        result=verified_screen_summary('已发送成功',[],'在ChatGPT当前对话框输入并发送')
        self.assertIn('未完成发送',result)
    def test_chatgpt_topic_document_is_not_a_chat_submission(self):
        result=verified_screen_summary('文档已准备好，等待发送',[],'写一份ChatGPT介绍文档，发送给我')
        self.assertEqual(result,'文档已准备好，等待发送')
    def test_work_loop_overrides_unsupported_model_success(self):
        import tempfile
        from pathlib import Path
        from work_assistant import WorkAssistant
        client=Mock();client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"tool":"finish","message":"已经在ChatGPT里发送成功"}'),finish_reason='stop')])
        with tempfile.TemporaryDirectory() as folder:
            a=WorkAssistant(client,'test',{'owner'},True,root=Path(folder))
            result,files=a.work('owner','在ChatGPT当前对话框输入并发送测试内容')
        self.assertIn('未完成发送',result);self.assertEqual(files,[])
    def test_receipt_ignores_editor_placeholder_and_sidebar(self):
        import sys
        def node(role,text='',children=(),rect=(200,300,500,350)):
            return SimpleNamespace(IsPassword=False,ControlTypeName=role,Name=text,GetChildren=lambda:list(children),BoundingRectangle=SimpleNamespace(left=rect[0],top=rect[1],right=rect[2],bottom=rect[3]))
        draft=node('EditControl',children=[node('TextControl','测试任务')])
        sidebar=node('TextControl','测试任务',rect=(0,200,50,250))
        below=node('TextControl','测试任务',rect=(200,550,500,580))
        root=node('PaneControl',children=[draft,sidebar,below])
        d,c=self.desktop();d.receipt_input_rect=(100,500,600,600)
        auto=SimpleNamespace(ControlFromHandle=lambda handle:root)
        with patch.dict(sys.modules,{'uiautomation':auto}):
            counts=d.transcript()
            self.assertEqual(counts,Counter())
            root.GetChildren=lambda:[draft,sidebar,below,node('TextControl','测试任务')]
            self.assertEqual(d.transcript()[message_text('测试任务')],1)
    def test_explicit_submit_intent(self):
        self.assertTrue(chat_submit_requested('在ChatGPT输入测试并发送'))
        self.assertFalse(chat_submit_requested('先输入测试，不要发送'))
        self.assertFalse(chat_submit_requested('只清空并填入草稿'))
if __name__=='__main__':unittest.main()
