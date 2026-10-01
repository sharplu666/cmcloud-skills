#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：download"""
from __future__ import annotations

from cli.cli_runtime import (
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    api_batch_download_url,
    emit_jsonl,
    exit_with_error,
    format_bytes,
    get_file_info_map,
    os,
    requests,
    snapshot_trace_id,
    sys,
    time,
)

def run(
    file_ids: list,
    download_dir: str,
) -> int:
    if not os.path.exists(download_dir):
        exit_with_error(f'下载失败，目录 {download_dir} 不存在', code=EXIT_INPUT_ERROR)
    if not file_ids:
        exit_with_error('下载失败：file_ids 不能为空', code=EXIT_INPUT_ERROR)

    try:
        urls = api_batch_download_url(file_ids)
        snapshot_trace_id()
        infos = get_file_info_map(file_ids)
        names = {fid: infos[fid]['fileName'] for fid in file_ids if fid in infos and 'fileName' in infos[fid]}

        if len(names) != len(file_ids):
            missing = set(file_ids) - set(names.keys())
            raise RuntimeError(f'文件ID {",".join(missing)} 不存在或无法获取文件名')
    except Exception as e:
        exit_with_error(f'下载失败: {e}')

    tty = sys.stderr.isatty()
    interval = 0.25 if tty else 5.0
    total = len(urls)
    results = []

    def progress(line: str, nl: bool = False):
        if tty:
            sys.stderr.write(f'\r\033[2K{line}' + ('\n' if nl else ''))
        else:
            sys.stderr.write(line + '\n')
        sys.stderr.flush()

    for idx, (fid, dl_url) in enumerate(urls.items(), 1):
        fname = names[fid]
        prefix = f'[{idx}/{total}] {fname}'

        try:
            with requests.get(dl_url, stream=True, timeout=120) as r:
                if r.status_code != 200:
                    results.append({'fileId': fid, 'status': 'error', 'message': f'HTTP {r.status_code}'})
                    continue

                total_bytes = int(r.headers.get('Content-Length', '0'))
                done = 0
                last_t = 0.0

                with open(os.path.join(download_dir, fname), 'wb') as f:
                    for chunk in r.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()

                        if now - last_t >= interval or (total_bytes and done >= total_bytes):
                            last_t = now
                            if total_bytes:
                                pct = min(100, done * 100 // total_bytes)
                                progress(f'{prefix}  {pct}%  {format_bytes(done)}/{format_bytes(total_bytes)}')
                            else:
                                progress(f'{prefix}  {format_bytes(done)}')

                tail = f'{format_bytes(done)}/{format_bytes(total_bytes)}' if total_bytes else format_bytes(done)
                progress(f'{prefix}  完成  {tail}', nl=True)

            results.append({'fileId': fid, 'fileName': fname, 'status': 'success', 'message': '下载成功', 'localDir': os.path.join(download_dir, fname)})
        except Exception as e:
            if tty:
                sys.stderr.write('\n')
            results.append({'fileId': fid, 'status': 'error', 'message': str(e)})

    ok_count = sum(1 for r in results if r.get('status') == 'success')
    fail_count = len(results) - ok_count
    status = 'success' if fail_count == 0 else ('error' if ok_count == 0 else 'warning')
    emit_jsonl({
        'record': 'meta', 'status': status, 'command': 'download',
        'downloadDir': download_dir, 'okCount': ok_count, 'failCount': fail_count,
    })
    for idx, r in enumerate(results, start=1):
        emit_jsonl({'record': 'result', 'index': idx, **r})

    return EXIT_BUSINESS_ERROR if fail_count else EXIT_OK
