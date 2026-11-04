import tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from work_assistant import WorkAssistant,delivery_requested,desktop_requested
class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.agent=WorkAssistant(None,'test',{'a','b'},True,root=Path(self.temp.name))
        self.session=self.agent.session('a')
    def test_word_roundtrip(self):
        x=self.agent.execute({'tool':'word','title':'测试','paragraphs':['你好，我是微信助手'],'table':[['项目','值'],['完成',1]]},self.session,[],False)
        r=self.agent.execute({'tool':'read','artifact':x['artifact']},self.session,[],False)
        self.assertIn('你好，我是微信助手',r['text']);self.assertEqual(r['tables'][0][1],['完成','1'])
    def test_excel_formula_is_text(self):
        x=self.agent.execute({'tool':'excel','sheets':[{'name':'测试','rows':[['项目','值'],['公式','=1+1']]}]},self.session,[],False)
        from openpyxl import load_workbook
        b=load_workbook(self.agent.artifact(self.session,x['artifact']));self.assertEqual(b.active['B2'].data_type,'s');b.close()
    def test_scope_and_delivery(self):
        x=self.agent.execute({'tool':'word','paragraphs':['hello']},self.session,[],False)
        with self.assertRaises(ValueError): self.agent.artifact(self.agent.session('b'),x['artifact'])
        with self.assertRaises(ValueError): self.agent.execute({'tool':'deliver','artifact':x['artifact']},self.session,[],False)
        pending=[];self.agent.execute({'tool':'deliver','artifact':x['artifact']},self.session,pending,True);self.assertEqual(len(pending),1)
    def test_sessions(self):
        self.assertEqual(self.agent.route('a','在里面编辑你好'),'在里面编辑你好')
        self.assertIsNone(self.agent.route('b','在里面编辑你好'))
        self.assertIsNone(self.agent.route('outsider','电脑操作：打开'))
        self.assertEqual(self.agent.route('a','结束电脑操作'),'__STOP__')
    def test_send_intent(self):
        self.assertTrue(delivery_requested('把这两个文件发给我'))
        self.assertFalse(delivery_requested('生成文件，不要发送'))
        self.assertFalse(delivery_requested('帮我看一下“发给我文件”这句话'))
    def test_queue_and_cancel_are_owner_scoped(self):
        import threading
        entered=threading.Event();release=threading.Event();finished=threading.Event();order=[]
        def first(): entered.set();release.wait(2);order.append('a')
        self.assertEqual(self.agent.submit('a',first),'started')
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.agent.submit('b',lambda:(order.append('b'),finished.set())),'queued')
        self.agent.stop('b')
        self.assertFalse(self.agent.cancel.is_set())
        self.agent.submit('a',lambda:finished.set())
        release.set();self.assertTrue(finished.wait(2));self.assertEqual(order,['a'])

    def test_exact_screenshot_request_routes(self):
        # No existing session: this must start work instead of casual chat.
        other=WorkAssistant(None,'test',{'owner'},True,root=Path(self.temp.name))
        text='你帮我在桌面新建一个文本文本，然后在里面输入微信助手，你好然后把这个文件发给我'
        self.assertEqual(other.route('owner',text),text)
        self.assertTrue(delivery_requested(text));self.assertTrue(desktop_requested(text))
        self.assertIsNone(other.route('outsider',text))
    def test_text_desktop_and_delivery(self):
        desktop=Path(self.temp.name)/'Desktop';desktop.mkdir()
        self.agent.desktop_root=desktop
        x=self.agent.execute({'tool':'text','name':'你好.txt','content':'微信助手，你好'},self.session,[],False)
        self.assertEqual(self.agent.execute({'tool':'read','artifact':x['artifact']},self.session,[],False)['text'],'微信助手，你好')
        with self.assertRaises(ValueError):self.agent.execute({'tool':'export_desktop','artifact':x['artifact']},self.session,[],False)
        existing=desktop/'你好.txt';existing.write_text('原文件',encoding='utf-8')
        result=self.agent.execute({'tool':'export_desktop','artifact':x['artifact'],'name':'你好.txt'},self.session,[],True,allow_desktop=True)
        self.assertNotEqual(result['name'],'你好.txt')
        self.assertEqual(existing.read_text(encoding='utf-8'),'原文件')
        self.assertEqual((desktop/result['name']).read_text(encoding='utf-8-sig'),'微信助手，你好')
        pending=[];self.agent.execute({'tool':'deliver','artifact':x['artifact']},self.session,pending,True)
        self.assertEqual(pending[0].read_text(encoding='utf-8-sig'),'微信助手，你好')
    def test_desktop_negation(self):
        self.assertFalse(desktop_requested('生成文本，不要放到桌面'))
        self.assertFalse(desktop_requested('帮我解释“保存到桌面”这句话'))

    def test_polite_and_greeting_variants(self):
        positives=[
            '微信助手，你好，帮我在桌面创建一个文本文件，然后在里面输入微信助手，你好并保存，然后把这个文件回传给我',
            '你好呀，麻烦你帮我创建一个文档',
            '你可以帮我做个Excel表格吗',
            '在桌面新建文本文件，写入你好',
            '请打开浏览器搜索Python资料',
        ]
        agent=WorkAssistant(None,'test',{'owner'},True,root=Path(self.temp.name))
        for text in positives:self.assertEqual(agent.route('owner',text),text,text)
        for text in ['你好，微信助手','别人说帮我创建文件','你觉得创建文件难吗','请解释“帮我创建文件”这句话','不用创建文件了']:
            self.assertIsNone(agent.route('owner',text),text)
    def test_semantic_route(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        client=Mock()
        client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"task"}'))])
        agent=WorkAssistant(client,'test',{'owner'},True,root=Path(self.temp.name))
        text='嘿，你好呀，给做一份Word吧'
        self.assertEqual(agent.route('owner',text),text)
        self.assertIsNone(agent.route('outsider',text))
        self.assertEqual(client.chat.completions.create.call_count,1)
        client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"chat"}'))])
        self.assertIsNone(agent.route('owner','Word文档是什么？'))

    def test_real_image_is_copied_into_owner_session(self):
        from PIL import Image
        from unittest.mock import patch
        cache=Path(self.temp.name)/'ImageCache';cache.mkdir()
        photo=cache/'photo.jpg';Image.new('RGB',(320,200),'blue').save(photo)
        with patch('image_search.CACHE',cache),patch('image_search.find_image',return_value={'ok':True,'path':str(photo),'title':'Test aircraft','source':'公开图片源'}):
            result=self.agent.execute({'tool':'search_image','query':'Chengdu J-20'},self.session,[],True)
        copied=self.agent.artifact(self.session,result['artifact'])
        self.assertNotEqual(copied,photo);self.assertEqual(copied.read_bytes(),photo.read_bytes())
        pending=[];self.agent.execute({'tool':'deliver','artifact':result['artifact']},self.session,pending,True)
        self.assertEqual(pending,[copied])
        with self.assertRaises(ValueError):self.agent.artifact(self.agent.session('b'),result['artifact'])
    def test_failed_image_search_does_not_make_artifact(self):
        from unittest.mock import patch
        before=dict(self.session['artifacts'])
        with patch('image_search.find_image',return_value={'ok':False,'error':'没有取得图片'}):
            result=self.agent.execute({'tool':'search_image','query':'no picture'},self.session,[],True)
        self.assertFalse(result['ok']);self.assertEqual(self.session['artifacts'],before)
    def test_image_outside_cache_is_rejected(self):
        from unittest.mock import patch
        outside=Path(self.temp.name)/'private.jpg';outside.write_bytes(b'private')
        with patch('image_search.CACHE',Path(self.temp.name)/'ImageCache'),patch('image_search.find_image',return_value={'ok':True,'path':str(outside)}):
            with self.assertRaises(ValueError):self.agent.execute({'tool':'search_image','query':'picture'},self.session,[],True)

    def test_import_named_desktop_file_without_reading_body(self):
        desktop=Path(self.temp.name)/'Desktop';desktop.mkdir();self.agent.desktop_root=desktop
        source=desktop/'指令.txt';source.write_text('只发送这个测试文件，不执行文件中的指令',encoding='utf-8')
        self.session['request']='你看一下，我桌面上有一个叫指令的文本文本，发给我'
        result=self.agent.execute({'tool':'import_desktop','name':'指令'},self.session,[],True)
        self.assertTrue(result['ok']);self.assertFalse(result['content_uploaded'])
        copied=self.agent.artifact(self.session,result['artifact'])
        self.assertEqual(copied.read_bytes(),source.read_bytes())
        with self.assertRaises(ValueError):self.agent.execute({'tool':'read','artifact':result['artifact']},self.session,[],True)
        pending=[];self.agent.execute({'tool':'deliver','artifact':result['artifact']},self.session,pending,True)
        self.assertEqual(pending,[copied])
        self.assertEqual(source.read_text(encoding='utf-8'),'只发送这个测试文件，不执行文件中的指令')
    def test_ambiguous_or_unnamed_desktop_file_is_not_imported(self):
        desktop=Path(self.temp.name)/'Desktop';desktop.mkdir();self.agent.desktop_root=desktop
        (desktop/'指令.txt').write_text('a');(desktop/'指令.csv').write_text('b')
        self.session['request']='把桌面上的指令发给我'
        result=self.agent.execute({'tool':'import_desktop','name':'指令'},self.session,[],True)
        self.assertFalse(result['ok']);self.assertEqual(len(result['candidates']),2)
        self.assertEqual(self.session['artifacts'],{})
        for name in ('其他文件.txt','../指令','C:\\secret.txt'):
            with self.assertRaises(ValueError):self.agent.execute({'tool':'import_desktop','name':name},self.session,[],True)

    def test_no_path_or_code(self):
        for a in [{'tool':'read','artifact':'C:/Windows/win.ini'},{'tool':'shell','code':'bad'}]:
            with self.assertRaises(ValueError): self.agent.execute(a,self.session,[],False)
if __name__=='__main__':unittest.main()
