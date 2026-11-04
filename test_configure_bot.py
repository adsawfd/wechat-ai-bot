import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import configure_bot

class ConfigureTests(unittest.TestCase):
    def call(self,folder,db,*args):
        with patch.object(configure_bot,'__file__',str(Path(folder)/'configure_bot.py')), \
             patch('sys.argv',['configure_bot.py',*args]), \
             patch('wechatauto.db.WeChatDB',return_value=db), \
             patch('bot_account.open_bound_database',return_value=db):
            configure_bot.main()

    def test_owner_is_bound_only_when_contact_matches_uniquely(self):
        db=Mock();db.get_self_info.return_value={'username':'bot'}
        db.search_contact.return_value=[{'username':'person','nick_name':'管理员甲','remark':''}]
        with tempfile.TemporaryDirectory() as folder:
            self.call(folder,db,'--bind-owners','管理员甲')
            cfg=json.loads((Path(folder)/'称呼配置.json').read_text(encoding='utf8'))
            self.assertEqual(cfg['boss_contacts'][0]['username'],'person')
            with self.assertRaises(SystemExit):self.call(folder,db,'--bind-owners','管理员甲')

    def test_ambiguous_contact_does_not_create_config(self):
        db=Mock();db.get_self_info.return_value={'username':'bot'}
        db.search_contact.return_value=[{'username':'one','nick_name':'重名'}, {'username':'two','nick_name':'重名'}]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(SystemExit):self.call(folder,db,'--bind-owners','重名')
            self.assertFalse((Path(folder)/'称呼配置.json').exists())
