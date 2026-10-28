"""Open the account explicitly bound to this bot when multiple accounts exist."""
import json
import os
import re
from pathlib import Path

from reply_identity import CONFIG_FILE


def open_bound_database(*, config_file=None, db_dir=None, db_factory=None):
    from wechatauto.db import WeChatDB, auto_detect_db_dir, _find_account_dirs

    factory = db_factory or WeChatDB
    config_file = Path(config_file or CONFIG_FILE)
    if not config_file.exists():
        # Preserve the default behavior for installations without a binding.
        return factory()
    try:
        config = json.loads(config_file.read_text(encoding='utf-8'))
        expected = config.get('account_id')
        if not isinstance(expected, str) or not expected:
            raise ValueError('missing account_id')
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeError('无法读取机器人绑定账号，停止启动以免监听错账号') from exc

    base = db_dir or auto_detect_db_dir()
    if not base:
        raise RuntimeError('找不到微信数据库，无法确认机器人绑定账号')
    # Use the same account-directory rule as WeChatDB.wxid, but only select
    # the account explicitly bound by the existing configuration.
    candidates = [os.path.basename(path) for path in _find_account_dirs(base)
                  if re.sub(r'_\w{4}$', '', os.path.basename(path)) == expected]
    if len(candidates) != 1:
        raise RuntimeError('机器人绑定账号的微信数据库不存在或不唯一，已停止启动')
    db = factory(db_dir=base, account=candidates[0])
    # The underlying library can switch accounts while recovering database keys.
    # Do not attach to the chat listener if recovery selected a different account.
    if db.get_self_info().get('username') != expected:
        raise RuntimeError('微信数据库恢复时切换了账号，已停止启动以免监听错账号')
    return db
