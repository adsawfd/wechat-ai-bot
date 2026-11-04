import unittest,sys
from types import SimpleNamespace
from unittest.mock import Mock,patch
from work_desktop import WindowDesktop
class Field:
    def __init__(self,text='',name='和 Codex 一起工作',readable=True):
        self.value=text;self.Name=name;self.readable=readable;self.IsPassword=False;self.NativeWindowHandle=11;self.ControlTypeName='EditControl';self.runtime=[1,2];self.readonly=False
    def GetRuntimeId(self):return self.runtime
    def GetValuePattern(self):
        if not self.readable:return None
        field=self
        class Pattern:
            @property
            def Value(self):return field.value
            @property
            def IsReadOnly(self):return field.readonly
        return Pattern()
class InputTests(unittest.TestCase):
    def setUp(self):
        self.field=Field();self.clip='原剪贴板';self.selected=False;self.calls=[]
        self.d=WindowDesktop.__new__(WindowDesktop);self.d.info={'pid':7};self.d.foreground=11;self.d.focus_runtime=(1,2)
        self.d.wp=SimpleNamespace(GetWindowThreadProcessId=lambda h:(0,7))
        self.d.guard=lambda:None
        self.d.gui=SimpleNamespace(hotkey=self.hotkey,press=self.press)
        self.auto=SimpleNamespace(GetFocusedControl=lambda:self.field)
        self.clipmodule=SimpleNamespace(paste=lambda:self.clip,copy=lambda text:setattr(self,'clip',text))
        self.patches=[patch.dict(sys.modules,{'uiautomation':self.auto,'pyperclip':self.clipmodule}),patch('work_desktop.time.sleep')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def hotkey(self,*keys):
        self.calls.append(keys)
        if keys==('ctrl','a'):self.selected=True
        if keys==('ctrl','v'):
            self.field.value=self.clip if self.selected else self.field.value+self.clip
            self.selected=False
    def press(self,key):
        self.calls.append((key,))
        if key=='backspace' and self.selected:self.field.value='';self.selected=False
    def test_placeholder_name_is_not_actual_text(self):
        self.assertEqual(self.d.read_value(self.field)[0],'')
        result=self.d.input_text('你好',replace=True)
        self.assertTrue(result['verified']);self.assertEqual(self.field.value,'你好')
        self.assertNotIn(('ctrl','a'),self.calls)
        self.assertNotIn(('enter',),self.calls)
        self.assertEqual(self.clip,'原剪贴板')
    def test_clear_old_draft_and_replace(self):
        self.field.value='旧草稿'
        result=self.d.input_text('新内容\n第二行',replace=True)
        self.assertTrue(result['verified']);self.assertEqual(self.field.value,'新内容\n第二行')
        self.assertEqual(self.calls,[('ctrl','a'),('backspace',),('ctrl','v')])
    def test_clear_only(self):
        self.field.value='删掉这段'
        result=self.d.input_text(clear_only=True)
        self.assertTrue(result['verified']);self.assertEqual(self.field.value,'')
        self.assertNotIn(('ctrl','v'),self.calls)
    def test_real_text_equal_to_hint_is_still_cleared(self):
        self.field.value=self.field.Name
        self.d.input_text('替换',replace=True)
        self.assertEqual(self.field.value,'替换');self.assertIn(('backspace',),self.calls)
    def test_unknown_value_does_not_block_paste_or_claim_verified(self):
        self.field.readable=False
        result=self.d.input_text('输入这段',replace=True)
        self.assertEqual(self.field.value,'输入这段');self.assertFalse(result['verified'])
    def test_refuse_wrong_focus_password_and_readonly(self):
        for setting,value in [('IsPassword',True),('readonly',True),('ControlTypeName','ButtonControl')]:
            self.field=Field();setattr(self.field,setting,value)
            with self.assertRaises(ValueError):self.d.input_text('不能输入',replace=True)
        self.assertEqual(self.calls,[])
    def test_action_dispatch_clear_first(self):
        self.d.typed=True;self.field.value='旧内容'
        self.d.act({'action':'type','text':'新内容','clear_first':True})
        self.assertEqual(self.field.value,'新内容');self.assertTrue(self.d.last_input['verified'])
        self.d.act({'action':'clear_input'})
        self.assertEqual(self.field.value,'');self.assertTrue(self.d.last_input['verified'])
    def test_focus_changed_does_not_type(self):
        self.field.runtime=[8]
        with self.assertRaises(ValueError):self.d.input_text('不能输入',replace=True)
        self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main()
