#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 子命令：batch_rename"""
from __future__ import annotations

from cli.cli_runtime import (
    Any,
    BATCH_RENAME_MAX,
    EXIT_BUSINESS_ERROR,
    EXIT_INPUT_ERROR,
    EXIT_OK,
    MclawEnvError,
    Optional,
    api_batch_file_update,
    append_operation_log,
    batch_is_under_ai_space,
    collect_deduped_file_path_entries,
    emit_file_list_card,
    emit_file_path_list_card,
    emit_jsonl,
    enriched_row_to_cli_file_record,
    enriched_row_to_operation_log_record,
    exit_with_error,
    get_enriched_files_by_ids,
    get_file_info_map,
    get_file_path_map,
    normalize_rename_target_name,
    os,
    post_operation_file_id_from_batch_update,
    resolve_current_session,
    snapshot_trace_id,
)
from services.atomic.batch_ops import (
    _append_folder_children_logs,
    _copy_into_ai_space,
)

def parse_batch_rename_spec(token: str) -> tuple[str, str]:
    t = token.strip()
    sep = ':' if ':' in t else ('：' if '：' in t else None)
    if sep is None:
        exit_with_error('错误：每项须为 fileId:新名称 格式（支持中英文冒号）', code=EXIT_INPUT_ERROR)
    file_id, _, name = t.partition(sep)
    if not file_id.strip() or not name.strip():
        exit_with_error('错误：fileId 和新名称均不能为空', code=EXIT_INPUT_ERROR)
    return file_id.strip(), name.strip()

def run(
    pairs: list[tuple[str, str]],
    session: str = '',
) -> int:
    # CLI --session 仅兼容保留，实际一律读 MCLAW_CURRENT_SESSION
    _ = session
    if not pairs:
        exit_with_error('错误：至少需要一项 fileId:新名称', code=EXIT_INPUT_ERROR)
    if len(pairs) > BATCH_RENAME_MAX:
        exit_with_error(f'错误：单次批量重命名最多 {BATCH_RENAME_MAX} 条', code=EXIT_INPUT_ERROR)

    file_ids = [fid for fid, _ in pairs]
    pre_failed: dict[str, dict[str, str]] = {}  # original_file_id -> {newName, message}
    original_name_map = {fid: name for fid, name in pairs}  # 保留原始名称用于失败输出

    ai_space_status_map = batch_is_under_ai_space(file_ids)
    file_ids_to_copy = [fid for fid in file_ids if not ai_space_status_map.get(fid, False)]

    raw_session_id = ''
    if file_ids_to_copy:
        # 空间外文件须复制到默认会话目录：env 缺失或非法均应明确报错
        try:
            raw_session_id = resolve_current_session(required=True)
        except MclawEnvError as e:
            exit_with_error(str(e), code=EXIT_INPUT_ERROR)

    effective_file_id_map = {fid: fid for fid in file_ids}

    if file_ids_to_copy:
        copied_id_map, copy_failures = _copy_into_ai_space(
            file_ids_to_copy,
            raw_session_id=raw_session_id,
            command='batch_rename.copy_files',
            messages={
                'exc': '复制失败：{detail}',
                'failed': '复制到 AI 空间结果文件目录失败：{detail}',
                'missing': '复制到 AI 空间结果文件目录后未返回新 fileId',
                'empty': '复制返回空结果',
            },
        )
        for fid, msg in copy_failures.items():
            pre_failed[fid] = {'newName': original_name_map.get(fid, ''), 'message': msg}
        effective_file_id_map.update(copied_id_map)

    # 建立 effective → original 反向映射，用于将后续失败归因到原始 fileId
    original_of: dict[str, str] = {}
    for fid in file_ids:
        eff = effective_file_id_map.get(fid, fid)
        original_of[eff] = fid

    # 移除预失败项
    effective_pairs = [
        (effective_file_id_map[fid], name) for fid, name in pairs
        if fid not in pre_failed
    ]
    effective_file_ids = list(dict.fromkeys(fid for fid, _ in effective_pairs))

    info_map = get_file_info_map(effective_file_ids) if effective_file_ids else {}
    missing = [fid for fid in effective_file_ids if fid not in info_map]
    if missing:
        for fid in missing:
            orig_fid = original_of.get(fid, fid)
            pre_failed[orig_fid] = {'newName': original_name_map.get(orig_fid, ''), 'message': f'fileId 不存在：{fid}'}
        effective_pairs = [(fid, name) for fid, name in effective_pairs if fid not in missing]
        effective_file_ids = list(dict.fromkeys(fid for fid, _ in effective_pairs))

    if effective_file_ids:
        effective_ai_space_status_map = batch_is_under_ai_space(effective_file_ids)
        disallowed_effective_file_ids = [
            fid for fid in effective_file_ids
            if not effective_ai_space_status_map.get(fid, False)
        ]
    else:
        disallowed_effective_file_ids = []

    if disallowed_effective_file_ids:
        if not raw_session_id:
            try:
                raw_session_id = resolve_current_session(required=True)
            except MclawEnvError as e:
                exit_with_error(str(e), code=EXIT_INPUT_ERROR)
        fallback_id_map, fallback_failures = _copy_into_ai_space(
            disallowed_effective_file_ids,
            raw_session_id=raw_session_id,
            command='batch_rename.fallback_copy',
            messages={
                'exc': '二次复制失败：{detail}',
                'failed': '二次复制失败：{detail}',
                'missing': '二次复制后未返回新 fileId',
                'empty': '二次复制返回空结果',
            },
        )
        for fid, msg in fallback_failures.items():
            orig_fid = original_of.get(fid, fid)
            pre_failed[orig_fid] = {'newName': original_name_map.get(orig_fid, ''), 'message': msg}

        # 二次复制成功的项用新 fileId 改写；未成功的从待改名集合移除（已计入 pre_failed），
        # 避免仍在 AI 空间外的文件被就地改名。
        updated_pairs = []
        for fid, name in effective_pairs:
            if fid in fallback_id_map:
                new_fid = fallback_id_map[fid]
                original_of[new_fid] = original_of.get(fid, fid)
                updated_pairs.append((new_fid, name))
            elif fid not in disallowed_effective_file_ids:
                updated_pairs.append((fid, name))
        effective_pairs = updated_pairs
        effective_file_ids = list(dict.fromkeys(fid for fid, _ in effective_pairs))

        info_map = get_file_info_map(effective_file_ids) if effective_file_ids else {}
        missing = [fid for fid in effective_file_ids if fid not in info_map]
        if missing:
            for fid in missing:
                orig_fid = original_of.get(fid, fid)
                pre_failed[orig_fid] = {'newName': original_name_map.get(orig_fid, ''), 'message': f'fileId 不存在：{fid}'}
            effective_pairs = [(fid, name) for fid, name in effective_pairs if fid not in missing]
            effective_file_ids = list(dict.fromkeys(fid for fid, _ in effective_pairs))

    parent_file_ids = [str((info_map.get(fid) or {}).get('parentFileId') or '').strip() or '/' for fid in effective_file_ids]
    parent_path_map = get_file_path_map(parent_file_ids, action='批量重命名')

    normalized_pairs = []
    for fid, name in effective_pairs:
        fixed_name, _auto_fixed = normalize_rename_target_name(info_map[fid], name)
        normalized_pairs.append((fid, fixed_name))

    id_to_ctx: dict[str, tuple[str, str, str, str]] = {}
    sub_requests: list[dict[str, Any]] = []
    for idx, (fid, final_name) in enumerate(normalized_pairs):
        rid = str(idx)
        parent_file_id = str((info_map.get(fid) or {}).get('parentFileId') or '')
        parent_path = parent_path_map.get(parent_file_id or '/', '/' if parent_file_id in ('', '/') else '')
        id_to_ctx[rid] = (fid, final_name, parent_file_id, parent_path)
        sub_requests.append({'id': rid, 'fileId': fid, 'name': final_name, 'fileRenameMode': 'force_rename'})

    batch_results: dict[str, dict[str, Any]] = {}
    api_err_text: Optional[str] = None
    try:
        batch_results = api_batch_file_update(sub_requests)
    except RuntimeError as e:
        api_err_text = str(e)

    ok, fail = 0, 0
    status_map: dict[str, dict[str, Any]] = {}
    rename_ok_request_fids: set[str] = set()
    post_rename_id_map: dict[str, str] = {}
    for idx in range(len(normalized_pairs)):
        rid = str(idx)
        fid, final_name, parent_file_id, parent_path = id_to_ctx[rid]
        row = batch_results.get(rid) or {}
        code = str(row.get('code') or '').strip()
        msg = str(row.get('message') or '').strip()
        if code == '0000':
            ok += 1
            rename_ok_request_fids.add(fid)
            post_rename_id_map[fid] = post_operation_file_id_from_batch_update(row, fid)
        else:
            fail += 1
        if api_err_text:
            msg_text = api_err_text
        elif code == '0000':
            msg_text = msg or '重命名成功'
        else:
            msg_text = msg or '重命名失败'
        status_map[fid] = {
            'newName': final_name,
            'message': msg_text,
        }

    snapshot_trace_id()

    # 计入预失败数
    pre_fail_count = len(pre_failed)
    fail += pre_fail_count

    status = 'success' if fail == 0 else ('error' if ok == 0 else 'warning')
    want = list(dict.fromkeys(fid for fid, _ in normalized_pairs))
    enriched = get_enriched_files_by_ids(want) if want else []
    by_id = {str(r.get('fileId') or '').strip(): r for r in enriched}
    success_fids = [fid for fid, _ in normalized_pairs if fid in rename_ok_request_fids]
    success_ordered = [by_id[fid] for fid in success_fids if fid in by_id]

    log_fids = list(dict.fromkeys(post_rename_id_map[fid] for fid in rename_ok_request_fids))
    log_enriched_by_id: dict[str, dict[str, Any]] = {}
    if log_fids:
        for log_row in get_enriched_files_by_ids(log_fids):
            log_fid = str(log_row.get('fileId') or '').strip()
            if log_fid:
                log_enriched_by_id[log_fid] = log_row
    path_entries = collect_deduped_file_path_entries(success_ordered)

    msg_parts = [f'成功 {ok}']
    if fail:
        msg_parts.append(f'失败 {fail}')
        if pre_fail_count:
            msg_parts.append(f'（其中 {pre_fail_count} 条在重命名前失败）')
    payload: dict[str, Any] = {
        'record': 'meta', 'status': status, 'command': 'batch_rename',
        'message': f'批量重命名完成：{"，".join(msg_parts)}', 'okCount': ok, 'failCount': fail,
    }
    if path_entries:
        payload['filePathList'] = path_entries
    if fail:
        payload['hint'] = f'共 {fail} 个文件重命名失败，详见下方 record=hint 行。'
    emit_jsonl(payload)

    hint_index = 0
    for orig_fid, info in pre_failed.items():
        hint_index += 1
        emit_jsonl({
            'record': 'hint',
            'index': hint_index,
            'command': 'batch_rename',
            'status': 'failed',
            'fileId': orig_fid,
            'newName': info.get('newName', ''),
            'message': info.get('message', ''),
            'stage': 'pre_rename',
        })
    for fid, final_name in normalized_pairs:
        if fid in rename_ok_request_fids:
            continue
        hint_index += 1
        orig_fid = original_of.get(fid, fid)
        st = status_map.get(fid) or {}
        emit_jsonl({
            'record': 'hint',
            'index': hint_index,
            'command': 'batch_rename',
            'status': 'failed',
            'fileId': orig_fid,
            'newName': st.get('newName') or final_name,
            'message': st.get('message') or '重命名失败',
            'stage': 'rename',
        })

    # fid → (parent_file_id, parent_path)，供操作日志 parentFileId/parentFileName 使用
    fid_to_parent: dict[str, tuple[str, str]] = {
        ctx[0]: (ctx[2], ctx[3]) for ctx in id_to_ctx.values()
    }

    file_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(success_ordered, start=1):
        fid = str(row.get('fileId') or '').strip()
        st = status_map.get(fid) or {}
        file_rec = enriched_row_to_cli_file_record(row, index=idx)
        file_rec['name'] = st.get('newName') or row.get('name', '')
        file_rows.append(file_rec)
        post_fid = post_rename_id_map[fid]
        log_row = dict(log_enriched_by_id.get(post_fid) or row)
        log_row['fileId'] = post_fid
        log_row['name'] = file_rec['name']
        parent_pfid, parent_path = fid_to_parent.get(fid, ('', ''))
        parent_pname = os.path.basename(parent_path.rstrip('/')) or parent_path
        append_operation_log(
            enriched_row_to_operation_log_record(
                log_row,
                in_folder=True,
                parent_file_id=parent_pfid,
                parent_file_name=parent_pname,
            )
        )

    if file_rows:
        emit_file_list_card(file_rows, total=len(file_rows), search=False, cli='batch_rename')
        if path_entries:
            # 路径数 >5 时 summary 末行追加按钮提示 CTA，对齐 cm_cloud_organize
            # （organize_card_copy.AGGREGATE_CTA）的卡片契约
            summary = None
            if len(path_entries) > 5:
                summary = ' \n '.join([
                    '文件已为您完成整理并重命名',
                    '你可以点击下方「查看整理结果」按钮，查看整理结果',
                ])
            emit_file_path_list_card(path_entries, cli='batch_rename', summary=summary)

    # 对于被重命名的文件夹，将其子文件也写入操作日志
    _append_folder_children_logs(
        rename_ok_request_fids,
        post_rename_id_map,
        log_enriched_by_id,
    )

    return EXIT_OK if fail == 0 else EXIT_BUSINESS_ERROR
