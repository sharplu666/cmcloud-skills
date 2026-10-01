#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用(app)后端 —— 云盘文件管理端到端自检。

验证「任意 IP + 账号会话」这一通用链路上，cm_cloud_manage 的核心文件操作全部可用：
  mkdir / batch_check_exists / batch_get / get_path / upload / download /
  batch_rename / batch_move / 清理(移入回收站)

用法::

    python selftest_generic_mode.py            # 全量（会上传/下载/改名/移动，最后清理）
    python selftest_generic_mode.py --no-clean # 保留测试产物（默认清理）

依赖 CM_CLOUD_SESSION_FILE 指向的登录会话（见 common_auth/.env）。
退出码：0 = 全部通过；1 = 有步骤失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from pathlib import Path

warnings.filterwarnings('ignore')

PACK = Path(__file__).resolve().parent
MANAGE = PACK / 'cm_cloud_manage' / 'scripts'
SESSION_ID = 'agent:main:' + str(uuid.uuid4())
TEST_DIR_NAME = '_codex_selftest_' + time.strftime('%Y%m%d%H%M%S')
TEST_DIR_PATH = '/AI空间/MClaw空间/' + TEST_DIR_NAME


def _env() -> dict:
    env = dict(os.environ)
    env['PYTHONUTF8'] = '1'
    env['MCLAW_CURRENT_SESSION'] = SESSION_ID
    return env


def run(*argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, 'main.py', *argv],
        cwd=str(MANAGE), env=_env(), capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def jline(out: str, record: str) -> dict:
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get('record') == record:
            return obj
    return {}


def hcy(path: str, payload: dict) -> dict:
    """直连原生网关（仅用于校验/清理，不参与被测路径）。"""
    sys.path.insert(0, str(PACK / 'common'))
    sys.path.insert(0, str(PACK / 'common_auth'))
    from cm_cloud_auth import get_app_common_header
    import requests
    r = requests.post('https://personal-kd-njs.yun.139.com/hcy' + path, json=payload,
                      headers=get_app_common_header(), timeout=30, verify=False)
    return r.json()


FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    print('[%s] %s%s' % ('PASS' if ok else 'FAIL', name, (' | ' + detail) if detail else ''))
    if not ok:
        FAILED.append(name)


def main() -> int:
    no_clean = '--no-clean' in sys.argv
    print('session =', SESSION_ID)
    print('testdir =', TEST_DIR_PATH)

    rc, out = run('mkdir', TEST_DIR_PATH)
    meta = jline(out, 'meta')
    check('mkdir 创建目录', meta.get('status') == 'success' and bool(meta.get('fileId')),
          'fileId=%s status=%s' % (meta.get('fileId'), meta.get('status')))
    dir_id = str(meta.get('fileId') or '')
    if not dir_id:
        print(out)
        return 1

    rc, out = run('batch_check_exists', '/:AI空间')
    row = jline(out, 'check')
    check('batch_check_exists 查存在', row.get('errCode') == '0000' and row.get('exist') is True,
          'AI空间 exist=%s' % row.get('exist'))

    rc, out = run('get_path', dir_id)
    p = jline(out, 'path')
    check('get_path 查路径', p.get('errCode') == '0000' and TEST_DIR_NAME in str(p.get('filePath', '')),
          'filePath=%s' % p.get('filePath'))

    payload = ('codex generic-mode selftest %s\n' % time.strftime('%Y-%m-%d %H:%M:%S')).encode('utf-8')
    local = Path(tempfile.gettempdir()) / ('_codex_selftest_%s.txt' % uuid.uuid4().hex[:8])
    local.write_bytes(payload)
    rc, out = run('upload', str(local))
    up = json.loads(out[out.index('{', out.index('{"record": "meta"')):]) if False else jline(out, 'meta')
    check('upload 上传文件', up.get('status') == 'success', 'message=%s' % up.get('message'))
    file_id = ''
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('{') and '"fileId"' in line and '"index"' in line:
            try:
                file_id = str(json.loads(line).get('fileId') or '')
            except Exception:
                pass
    check('upload 返回 fileId', bool(file_id), 'fileId=%s' % file_id)
    if not file_id:
        print(out)
        return 1

    rc, out = run('batch_get', file_id)
    got = jline(out, 'meta')
    check('batch_get 取详情', got.get('status') == 'success', 'message=%s' % got.get('message'))

    dl_dir = Path(tempfile.gettempdir()) / ('_codex_dl_%s' % uuid.uuid4().hex[:8])
    dl_dir.mkdir(parents=True, exist_ok=True)
    rc, out = run('download', file_id, str(dl_dir))
    res = jline(out, 'result')
    saved = dl_dir / local.name
    check('download 下载文件', res.get('status') == 'success' and saved.exists()
          and saved.read_bytes() == payload, 'bytes=%s' % (saved.stat().st_size if saved.exists() else -1))

    new_name = 'renamed_' + local.name
    rc, out = run('batch_rename', '%s:%s' % (file_id, new_name))
    rn = jline(out, 'meta')
    check('batch_rename 重命名', rn.get('status') == 'success', 'message=%s' % rn.get('message'))

    rc, out = run('mkdir', '/AI空间/MClaw空间/_codex_selftest_target_' + time.strftime('%H%M%S'))
    target_meta = jline(out, 'meta')
    target_id = str(target_meta.get('fileId') or '')
    if target_id:
        rc, out = run('batch_move', file_id, target_id)
        mv = jline(out, 'meta')
        check('batch_move 移动文件', mv.get('status') == 'success', 'message=%s' % mv.get('message'))
    else:
        check('batch_move 移动文件', False, '目标目录创建失败')

    if not no_clean:
        ids = [i for i in (dir_id, target_id) if i]
        if ids:
            cleaned = hcy('/recyclebin/batchTrash', {'fileIds': ids})
            check('清理（移入回收站）', str(cleaned.get('code')) == '0000',
                  'task=%s' % ((cleaned.get('data') or {}).get('taskId')))
    try:
        local.unlink()
    except OSError:
        pass

    print()
    if FAILED:
        print('RESULT: FAIL ->', ', '.join(FAILED))
        return 1
    print('RESULT: ALL PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
