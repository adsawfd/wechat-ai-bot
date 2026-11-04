import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime,timezone
from token_usage import TokenUsage,MeteredClient,is_usage_query
class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=datetime(2026,10,29,15,59,59,tzinfo=timezone.utc).timestamp()
        self.file=Path(self.temp.name)/'usage.sqlite3'
        self.ledger=TokenUsage('bot',self.file,clock=lambda:self.now)
    def response(self,rid='one'):
        return SimpleNamespace(id=rid,model='test',usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20,prompt_cache_hit_tokens=30))
    def test_totals_cache_and_duplicate_response(self):
        self.ledger.record(self.response());self.ledger.record(self.response())
        r=self.ledger.today();self.assertEqual((r['input'],r['output'],r['cached'],r['requests']),(100,20,30,1))
        self.assertIn('合计：120',self.ledger.report())
    def test_restart_day_boundary_and_scope(self):
        self.ledger.record(self.response())
        same=TokenUsage('bot',self.file,clock=lambda:self.now);self.assertEqual(same.today()['input'],100)
        self.now+=2;self.assertEqual(same.today()['day'],'2026-10-30');self.assertEqual(same.today()['input'],0)
        self.ledger.record(self.response('two'));self.assertEqual(same.today()['input'],100)
        other=TokenUsage('other',self.file,clock=lambda:self.now);self.assertEqual(other.today()['input'],0)
    def test_missing_usage_and_failures_are_not_fake_zero(self):
        self.ledger.record(SimpleNamespace(id='missing',usage=None))
        self.ledger.record(status='failed')
        self.assertEqual(self.ledger.today()['unknown'],2)
        self.assertIn('token 数未知',self.ledger.report())
    def test_wrapper_records_and_preserves_options(self):
        raw=Mock();raw.chat.completions.create.return_value=self.response()
        client=MeteredClient(raw,self.ledger)
        self.assertIs(client.chat.completions.create(model='test'),raw.chat.completions.create.return_value)
        clone=Mock();clone.chat.completions.create.return_value=self.response('two');raw.with_options.return_value=clone
        client.with_options(timeout=4).chat.completions.create(model='test')
        self.assertEqual(self.ledger.today()['requests'],2)
        raw.chat.completions.create.side_effect=RuntimeError('offline')
        with self.assertRaises(RuntimeError):client.chat.completions.create(model='test')
        self.assertEqual(self.ledger.today()['unknown'],1)
    def test_query_and_report_do_not_call_model(self):
        for text in ['查询今日token消耗','今天token用了多少','微信助手，把今天的token使用量发出来','/token']:
            self.assertTrue(is_usage_query(text),text)
        for text in ['token是什么','别人说查询今日token消耗','解释“查询今日token消耗”这句话']:
            self.assertFalse(is_usage_query(text),text)
        self.assertIn('此前未记录',self.ledger.report())
if __name__=='__main__':unittest.main()
