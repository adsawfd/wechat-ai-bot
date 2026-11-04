import json
import tempfile
import unittest
from pathlib import Path
from respectful_contact import RespectfulContacts


class RespectfulTests(unittest.TestCase):
    def test_bound_account_and_sender_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'preference.json'
            path.write_text(json.dumps({'account_id':'owner','contacts':[{'username':'target'}]}), encoding='utf-8')
            pref = RespectfulContacts.load('owner', path)
            self.assertIn('不顶嘴', pref.style_for('target'))
            self.assertEqual(pref.style_for('someone-else'), '')
            self.assertEqual(RespectfulContacts.load('other-account', path).style_for('target'), '')

    def test_title_is_bound_to_verified_contact(self):
        pref=RespectfulContacts(['target'],{'target':'尊重称呼','outsider':'尊重称呼'})
        self.assertEqual(pref.address('在呢','target'),'尊重称呼，在呢')
        self.assertEqual(pref.address('尊重称呼，在呢','target'),'尊重称呼，在呢')
        self.assertEqual(pref.address('在呢','outsider'),'在呢')
        self.assertIn('尊重称呼',pref.style_for('target'))
        self.assertEqual(pref.title_for('outsider'),'')

    def test_missing_and_invalid_config_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'preference.json'
            self.assertFalse(RespectfulContacts.load('owner', path).ids)
            path.write_text('{bad', encoding='utf-8')
            self.assertFalse(RespectfulContacts.load('owner', path).ids)
