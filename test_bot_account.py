import json
import tempfile
import unittest
from pathlib import Path

from bot_account import open_bound_database


class AccountSelectionTests(unittest.TestCase):
    def test_bound_account_selected_even_if_another_account_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('mybot_1234', 'other_5678'):
                (root / name / 'db_storage').mkdir(parents=True)
            settings = root / 'config.json'
            settings.write_text(json.dumps({'account_id': 'mybot'}), encoding='utf-8')
            calls = []

            class DB:
                def __init__(self, **kwargs):
                    calls.append(kwargs)

                def get_self_info(self):
                    return {'username': 'mybot'}

            open_bound_database(config_file=settings, db_dir=str(root), db_factory=DB)
            self.assertEqual(calls, [{'db_dir': str(root), 'account': 'mybot_1234'}])

    def test_ambiguous_directory_or_recovery_to_another_account_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'mybot_1234' / 'db_storage').mkdir(parents=True)
            settings = root / 'config.json'
            settings.write_text(json.dumps({'account_id': 'mybot'}), encoding='utf-8')

            class SwitchedDB:
                def __init__(self, **kwargs):
                    pass

                def get_self_info(self):
                    return {'username': 'someone_else'}

            with self.assertRaisesRegex(RuntimeError, '切换了账号'):
                open_bound_database(config_file=settings, db_dir=str(root), db_factory=SwitchedDB)
            (root / 'mybot_5678' / 'db_storage').mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, '不唯一'):
                open_bound_database(config_file=settings, db_dir=str(root), db_factory=SwitchedDB)


if __name__ == '__main__':
    unittest.main()
