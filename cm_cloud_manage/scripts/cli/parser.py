#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 参数解析 —— argparse 子命令注册与入参规范化。"""
from __future__ import annotations


import argparse

from cli.cli_runtime import (
    CliArgumentParser,
    EXIT_INPUT_ERROR,
    exit_with_error,
    normalize_cloud_parent_file_id,
    validate_cloud_file_ids,
)


def build_parser() -> argparse.ArgumentParser:
    epilog = """
输出说明:
  · stdout：文件卡片 + meta JSONL；写操作回执亦可能含卡片
  · stderr：下载进度等过程日志

上传:
  · upload <本地绝对路径> [目标云盘目录] 上传到指定云盘目录（缺省为当前会话默认保存目录）

mkdir：完整路径须以 /AI空间/MClaw空间 开头

更多参数: python3 main.py <子命令> -h
"""
    root = CliArgumentParser(
        prog='main.py',
        description='中国移动云盘个人云 CLI：上传、下载、移动、复制、创建目录、重命名等原子操作',
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = root.add_subparsers(dest='command', metavar='子命令')

    p = sub.add_parser(
        'upload',
        help='把本地文件上传到云盘指定目录（写操作，须用户确认）',
        description='上传本地文件到云盘指定目录；目标目录可为云盘路径（如 /LinuxDo）或目录 fileId，不存在时自动创建；缺省为当前会话默认保存目录',
    )
    p.add_argument('file_path', help='本地文件的绝对路径')
    p.add_argument(
        'target_dir',
        nargs='?',
        default=None,
        help='目标云盘目录：云盘路径或目录 fileId，缺省为当前会话默认保存目录',
    )
    p.add_argument(
        '--session',
        default=None,
        help=argparse.SUPPRESS,
    )

    p = sub.add_parser(
        'download',
        help='把云盘文件下载到本地目录',
        description='按 fileId 批量下载到本地目录',
    )
    p.add_argument('file_ids', help='要下载的文件 fileId，多个用英文逗号分隔')
    p.add_argument('download_dir', help='本地保存目录的绝对路径，须已存在')

    p = sub.add_parser(
        'batch_get',
        help='按 fileId 批量查询文件详情',
        description='已知 fileId 时精确查元数据',
    )
    p.add_argument('file_ids', help='文件 fileId，多个用英文逗号分隔')

    p = sub.add_parser(
        'get_path',
        help='按 fileId 查询云盘完整路径',
        description='返回 namePath 等路径信息；单次最多 100 个 fileId',
    )
    p.add_argument('file_ids', help='文件或文件夹 fileId，多个用英文逗号分隔，最多 100 个')

    p = sub.add_parser(
        'batch_check_exists',
        help='检查某父目录下是否存在指定名称的直接子项',
        description='只查一层、不递归；格式 parentFileId:名称（parentFileId 支持 / 或 root 表示根目录）',
    )
    p.add_argument(
        'specs',
        nargs='+',
        help='一项或多项目，格式 父目录fileId:文件或文件夹名；多项用空格分隔，或一项内英文逗号分隔',
    )

    p = sub.add_parser(
        'create_default_save_dir',
        help='创建默认保存目录',
        description='创建或确保默认保存目录存在，返回 defaultFolderPath、defaultFolderFileId',
    )
    p.add_argument('session', nargs='?', default='', help=argparse.SUPPRESS)

    p = sub.add_parser(
        'get_default_save_dir',
        help='查询默认保存目录（不创建）',
        description='只查询不创建：返回 defaultFolderPath、defaultFolderFileId（不创建目录时为空）',
    )
    p.add_argument('session', nargs='?', default='', help=argparse.SUPPRESS)

    p = sub.add_parser(
        'batch_copy',
        help='批量复制文件到目标文件夹（写操作，须用户确认）',
        description='异步任务；目标父目录须在 /AI空间/MClaw空间 下，源文件不限所在目录；'
                    '单次最多 30 个文件，超出请改用「云盘文件管理」整理流程',
    )
    p.add_argument('file_ids', help='待复制文件的 fileId，多个用英文逗号分隔')
    p.add_argument('to_parent_file_id', help='目标父目录 fileId；须在 /AI空间/MClaw空间 下')
    p.add_argument('session', nargs='?', default='', help=argparse.SUPPRESS)

    p = sub.add_parser(
        'batch_move',
        help='批量移动文件到目标文件夹（写操作，须用户确认）',
        description=(
            '异步任务；源文件与目标父目录均须在 /AI空间/MClaw空间 下。'
            '源文件在该空间外时会跳过并提示改用 batch_copy；'
            '单次最多 30 个文件，超出请改用「云盘文件管理」整理流程'
        ),
    )
    p.add_argument('file_ids', help='待移动文件的 fileId，多个用英文逗号分隔')
    p.add_argument('to_parent_file_id', help='目标父目录 fileId；须在 /AI空间/MClaw空间 下')
    p.add_argument('session', nargs='?', default='', help=argparse.SUPPRESS)

    p = sub.add_parser(
        'mkdir',
        help='按完整云盘路径创建目录（写操作，须用户确认）',
        description=(
            '仅接受完整路径，须以 /AI空间/MClaw空间 开头；'
            '逐级 ensure，段名含空格时若同级存在去空格同名目录则复用不新建'
        ),
    )
    p.add_argument(
        'dir_path',
        help='完整云盘目录路径，如 /AI空间/MClaw空间/合同/2026',
    )

    p = sub.add_parser(
        'batch_rename',
        help='批量重命名文件（写操作，须用户确认）',
        description='单次最多 100 条；格式 FILEID:新名称，支持中英文冒号',
    )
    p.add_argument('--session', dest='session', default=None, help=argparse.SUPPRESS)
    p.add_argument(
        'specs',
        nargs='*',
        default=[],
        help='重命名项，格式 fileId:新文件名；多项用空格分隔；支持中英文冒号',
    )

    p = sub.add_parser(
        'play_media',
        help='按 fileId 播放单条视频/音频（batch_get 校验类型）',
        description='按 fileId 触发前端播放单条视频/音频；--content-type 必填'
                    '（audio=音频 / video=视频），非视频/音频或与实际类型不一致时报错',
    )
    p.add_argument('file_id', help='待播放的云盘文件 fileId')
    p.add_argument(
        '--content-type', default='',
        help='（必填）audio=音频 / video=视频；必须与 fileId 实际类型一致',
    )

    p = sub.add_parser(
        'organize',
        help='整理方向推荐/个人云目录/相册/回忆故事（四阶段：plan/submit/status/retry）',
        description='四阶段由 --step 显式路由：plan 产整理预案，submit 提交 plan 快照，'
                    'status/retry 按 --task-id 查询/重试；--target 选整理目标 '
                    'recommend（方向推荐仅预览）/drive/album/memory（必填），--from 承接 '
                    'search.jsonl 或 refine 子集 select/dedup.jsonl',
    )
    p.add_argument('--step', default=None, help='四阶段之一：plan / submit / status / retry（必填，显式路由）')

    # plan
    p.add_argument('--from', dest='from_handle', default=None, help='plan 用 op_<6位编码>/search.jsonl（原始结果）或 op_<6位编码>/select.jsonl / dedup.jsonl（refine 子集，复用其 bucket 标签不再聚类/精选）；submit 用 op_<6位编码>/plan.jsonl（plan 阶段产物）；四个 target 同形态；零拷贝就地读')
    p.add_argument('--target', default=None, help='plan：必填（四选一）recommend 整理方向推荐（用户没说去向时：三情形并列由用户选定，仅预览不落盘，不产 plan.jsonl）/ drive 整理到个人云目录 / album 相册（仅图片）/ memory 回忆故事（仅图片，自动去重精选）；recommend|album|memory 不支持 --parent-path/--rename-template，album|memory 的 search.jsonl 不分桶须 --merge-into <名>（recommend 不在此限，带标签子集册名来自标签）；retry：必填 drive/album/memory（取 submit 回执 data.target），仅用于任务卡与文案渲染')
    p.add_argument('--mode', default=None, help='plan：cross 交叉（拼名单层）/ hierarchical 层级（嵌套目录）；单维度或多维默认层级时无需传；缺省且无 --bucket = 不分桶（drive 文件直接进根目录；album|memory 单桶 search.jsonl 须配 --merge-into，recommend 不在此限，带标签子集不用）。读带 bucket 标签的子集时忽略（用子集自带 bucket）；flat 子集（整集 refine）仍按此参聚类')
    p.add_argument('--bucket', default=None, help='plan：分桶维度，单值（如 fileExtension）或 CSV（如 year,fileExtension）；单维度=单层子目录/相册、多维默认嵌套（可用 --mode cross 改拼名）；不传=不分桶。读带 bucket 标签的子集时忽略此参；子集无标签（整集 refine）时按此参聚类')
    p.add_argument('--parent-path', dest='parent_path', default=None, help='plan（仅 drive）：整理父目录（绝对路径须在 /AI空间/MClaw空间 下，相对路径拼到会话默认目录后）')
    p.add_argument('--rename-template', default=None, help='plan（仅 drive）：桶内文件重命名模板；占位符 {bucket}/{index}/{name}/{ext} 及 --bucket 维度名（如 {month}），非法占位符报错并列出全部支持项')
    p.add_argument('--unknown', dest='unknown_action', default='keep', help='plan：未知桶处理 keep（默认保留）/ drop（排除）')
    p.add_argument('--only', dest='only', default=None, help='plan：只保留预览编号命中的桶，CSV 如 1,3（编号 1 起，见 plan 回执 renderText）')
    p.add_argument('--merge-into', dest='merge_into', default=None, help='plan：把所有桶合并成一个以该名称命名的平铺文件夹/单个相册（丢弃分组结构）。配 refine select 子集时 = 先每桶精选再合并')

    # submit
    p.add_argument('--processing-hint', default=None, help='submit：等待整理中的提示语（≤250 字符，超长截断）')
    p.add_argument('--dry-run', action='store_true', help='submit：仅校验规划，不提交')

    # status / retry
    p.add_argument('--task-id', default=None, help='status/retry：任务 ID')

    p = sub.add_parser(
        'refine',
        help='对语料去重/精选（dedup/select），或合并多 jsonl 产新语料 merged.jsonl（merge）',
        description='refine 三种 kind：dedup 去重 / select 精选（须配 --pick），'
                    '输入为语料类文件（search.jsonl / merged.jsonl），传 --bucket 每桶'
                    '各自处理，不传整集处理，产 dedup.jsonl/select.jsonl；merge 合并多个'
                    '数据 jsonl（CSV ≥2 项：search/dedup/select/merged 任意组合），'
                    '产新会话 merged.jsonl（isFull 恒 true），可再 refine / plan / 再 merge',
    )
    p.add_argument('--kind', default='', help='dedup（去重）/ select（精选，须配 --pick）/ merge（合并多 jsonl 产新语料）；三选一')
    p.add_argument('--from', dest='from_handle', default='', help='dedup/select：单个语料文件（如 op_<6位编码>/search.jsonl 或 op_<6位编码>/merged.jsonl）；merge：CSV ≥2 项（如 op_<6位编码1>/search.jsonl,op_<6位编码2>/select.jsonl），文件限 search/dedup/select/merged.jsonl')
    p.add_argument('--mode', default=None, help='分桶模式 cross/hierarchical（与 organize --mode 同义，仅 per-bucket refine 用）；单维度无需传；hierarchical 在子集中降维成单层拼名')
    p.add_argument('--bucket', default=None, help='分桶维度（单值或 CSV）；传则 per-bucket refine（子集每行带 bucket 标签），不传则整集 refine（子集无桶标签）')
    p.add_argument('--pick', default='', help='select：每桶精选前 N 张（正整数）；dedup 不传；select 必填')

    # ── 检索命令（原始字符串收参：无 choices/type/required，校验在 services/search/args）──
    p_semantic = sub.add_parser(
        'semantic-search',
        help='语义搜图：一句自然语言找图（仅 --query 与 --mode，无过滤参数）',
        description='--query 必填（自然语言整句，时间/地点/人物等约束写进句内）；'
                    '不支持任何结构化过滤（类型/时间/大小/目录范围/备份口径），按文件名搜索请改用 search --keyword；'
                    '--mode view=单页快速返回（默认）/ full=全量拉取+落盘+断点续传',
    )
    p_semantic.add_argument('--query', default=None, help='语义搜索文本（自然语言整句，必填）')
    p_semantic.add_argument('--mode', default='view', help='view=单页快速返回（默认）；full=全量拉取+落盘+断点续传')

    p_search = sub.add_parser(
        'search',
        help='云盘文件/图片条件检索：--keyword+过滤参数',
        description='--keyword 文件名关键字可与过滤参数组合（--type image 纯图片走图片检索拿富化行）；'
                    '语义搜图（一句自然语言找图）请改用 semantic-search；'
                    '--mode view=单页快速返回（默认）/ full=全量拉取+落盘+断点续传',
    )
    p_search.add_argument('--keyword', default=None, help='文件名/标题关键字（可空=纯条件筛选；可与过滤参数组合）')
    p_search.add_argument('--mode', default='view', help='view=单页快速返回（默认）；full=全量拉取+落盘+断点续传')
    p_search.add_argument('--type', default=None, help='类型 CSV：image/audio/video/doc/folder/other（如 image,doc；不传=综合）')
    p_search.add_argument('--ext', default=None, help='扩展名 CSV，如 jpg,png（前导 . 可省）')
    p_search.add_argument('--start-at', default=None, help='时间过滤起点（支持日期简写）')
    p_search.add_argument('--end-at', default=None, help='时间过滤终点（支持日期简写；缺省=当前时间）')
    p_search.add_argument('--time-field', default=None, help='createdAt / updatedAt / takenAt（拍摄时间仅纯图片可用）；不传时随 --type：纯图片=takenAt，其余=updatedAt')
    p_search.add_argument('--size-min', default=None, help='大小下限，如 10MB')
    p_search.add_argument('--size-max', default=None, help='大小上限，如 2G')
    p_search.add_argument('--scope-in', default=None, help='限定目录范围 fileId CSV（与 --scope-out 互斥，最多 20 个）')
    p_search.add_argument('--scope-out', default=None, help='排除目录范围 fileId CSV（与 --scope-in 互斥，最多 20 个）')
    p_search.add_argument('--recursive', default=None, help='true=递归检索全部子目录；不传=只在所选目录一层内检索（默认）')
    p_search.add_argument(
        '--backup-folder', dest='backup_folder', action='append', default=None, metavar='NAME',
        help='备份来源目录中文名，可重复：手机备份/手机图片/手机音乐/手机视频/同步盘/139 邮箱/来自电脑备份/来自微信备份文件夹；不传=不限定备份口径；与 --scope-in/--scope-out 互斥',
    )

    p_dynamic = sub.add_parser(
        'dynamic',
        help='个人动态搜索：时间窗内查看/上传过的动态（--type image 图片动态 / audio 音频动态 / video 视频动态 / doc 文档动态；不传=全部文件动态）',
        description='--start-at 必填且须绝对时间（「最近一周」等相对说法由调用方换算成绝对值传入）；'
                    '--kind view=查看动态（默认）/ upload=上传动态；'
                    '--mode view=单页快速返回（默认）/ full=全量拉取+落盘+断点续传',
    )
    p_dynamic.add_argument('--start-at', default='', help='时间窗起点，绝对时间，如 "2026-08-01 00:00:00"（支持日期简写）')
    p_dynamic.add_argument('--end-at', default='', help='时间窗终点，绝对时间（支持日期简写；缺省=当前时间）')
    p_dynamic.add_argument('--keyword', default='', help='关键字，缺省不限')
    p_dynamic.add_argument('--kind', default='view', help='view=查看动态，upload=上传动态')
    p_dynamic.add_argument('--type', default=None, help='动态类型：image（图片动态）/ audio（音频动态）/ video（视频动态）/ doc（文档动态）；不传=全部文件动态（目录与其他类型暂不支持）')
    p_dynamic.add_argument('--mode', default='view', help='view=单页快速返回（默认）；full=全量拉取+落盘+断点续传')

    # ── 转存查询（裸字符串收参，校验在 services/search_transfer/args）──
    p_st = sub.add_parser(
        'search-transfer',
        help='搜索转存：按转存来源查转存的文件（--transfer-type 5=分享转存 / 6=圈子转存 / 7=发现转存，纯查询不落盘）',
        description='查询转存动态（5=分享转存 / 6=圈子转存 / 7=发现转存，单次只查一种）；'
                    '--start-at 必填且须绝对时间；--end-at 缺省=当前时间；'
                    '纯查询不落盘、无 --mode view/full，翻页用回执 next.next-page 给出的 --page-after 游标',
    )
    p_st.add_argument('--keyword', default='', help='文件名关键字，缺省空（仅匹配文件名）')
    p_st.add_argument('--start-at', default='', help='查询开始时间，绝对时间，如 "2026-08-01 00:00:00"（支持日期简写；必填）')
    p_st.add_argument('--end-at', default='', help='查询结束时间，绝对时间（支持日期简写；缺省=当前时间）')
    p_st.add_argument('--transfer-type', default='', help='转存类型单值：5=分享转存 / 6=圈子转存 / 7=发现转存（必填，单次只查一种）')
    p_st.add_argument('--page-size', default='10', help='每页条数 1-100（默认 10）')
    p_st.add_argument('--page-after', default='', help='翻页游标（上页回执 next.next-page 给出，原样透传）')

    # ── 图文搜人（裸字符串收参，校验在 services/person_search/args）──
    p_person = sub.add_parser(
        'person-search',
        help='图文搜人：参考图+描述搜人物照片（--file-ids 首搜 / --select-faces 选脸二次）',
        description='--query 必填（首搜为用户原描述 queryA；选脸二次为用户澄清后的 queryB，'
                    'CLI 内部按 queryA#queryB 拼接，# 后端拆段协议须保留）；'
                    '--file-ids（参考图首搜，内部先人脸识别，需要澄清时出选脸卡等用户选择）'
                    '与 --select-faces（选脸二次搜索，必须与 --from 同传）互斥、必传其一；'
                    '--file-ids 首搜须同传 --bindings（人物指称与图的对应，'
                    '<imgN> 与 fileId 一一对应）；'
                    '需要澄清后选脸二次须带 --from op_<6位编码>/ambiguity.jsonl 承接上一轮 queryA（与 --select-faces 同传）；'
                    '--mode view=单页快速返回（默认）/ full=全量拉取+落盘+断点续传',
    )
    p_person.add_argument('--query', default='', help='自然语言描述（首搜=queryA；选脸二次=queryB，CLI 内部按 queryA#queryB 拼接，# 后端拆段协议须保留）')
    p_person.add_argument('--file-ids', default='', help='参考图 fileId CSV（首次搜索，图片理解路径）；与 --select-faces 互斥')
    p_person.add_argument('--bindings', default='', help='人物指称与图的对应关系：<imgN>指称原话</imgN>（N=该图在 --file-ids 中的次序，不含 fileId 本身）；须与 --file-ids 一一对应，首搜必传；与 --select-faces/--from 互斥')
    p_person.add_argument('--select-faces', default='', help='选脸二次搜索的人脸框 JSON 数组（用户在 selectFaceList 卡勾选后传入）；必须与 --from 同传，与 --file-ids 互斥')
    p_person.add_argument('--from', dest='from_handle', default='', help='承接上一轮需要澄清状态：op_<6位编码>/ambiguity.jsonl；与 --select-faces 同传，CLI 内部拼 queryA#queryB')
    p_person.add_argument('--mode', default='view', help='view=单页快速返回（默认）；full=全量拉取+落盘+断点续传')

    # ── 按 fileId 精确取文件详情（仅 --file-ids 一参，校验在 services/search_by_ids）──
    p_ids = sub.add_parser(
        'search-by-ids',
        help='按 fileId 精确取文件详情（含 AI 分析信息），产 search.jsonl 语料；仅文件 id，folder 报错并指路 search',
        description='--file-ids 必填（文件 fileId CSV，CLI 上限 20）；batchGet 校验存在性，任一不存在整体拒绝；'
                    'type=folder 的项整体拒绝，回执 next.search 指路 search --scope-in --recursive --mode full；'
                    '与 batch_get 的区别是产 op_<6位>/search.jsonl 语料可交接 refine/organize；'
                    '同步全量取数：无 --mode、无翻页、不发卡片',
    )
    p_ids.add_argument('--file-ids', default='', help='文件 fileId CSV（英文逗号分隔，上限 20）')

    sub.add_parser('help', help='显示本帮助与子命令列表')
    return root


def parse_csv_file_ids(raw: str, *, field_name: str = 'file_ids') -> list[str]:
    normalized = (raw or '').replace('，', ',')
    ids = [x.strip() for x in normalized.split(',') if x.strip()]
    if not ids:
        exit_with_error(f'错误：{field_name} 不能为空', code=EXIT_INPUT_ERROR)
    try:
        return validate_cloud_file_ids(ids, context=field_name)
    except ValueError as e:
        exit_with_error(f'错误：{e}', code=EXIT_INPUT_ERROR)
