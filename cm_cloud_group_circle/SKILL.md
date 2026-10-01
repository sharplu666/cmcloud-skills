---
name: 云盘群组管理
description: >
  查询、搜索中国移动云盘群组，并向群组发布动态（图片/视频/文件）。
  圈子、家庭云、群组、共享群、家庭圈均为同一协作空间，用户任意一种叫法均触发本技能。
  对用户回复时统一使用「群组」。
  支持已加入列表、已创建列表与关键词搜索。
  触发场景：云盘群组、圈子、共享群、家庭云、家庭圈、群组动态、发圈、发布动态、
  查群组、发文件到群组、发视频到圈子、相册发圈等。
user-invocable: true
metadata:
  openclaw:
    emoji: "🫂"
---

# 云盘群组管理

查询已加入 / 已创建的群组、按关键词搜索，并向指定群组发布动态。对用户一律称「群组」；CLI 参数仍用 `groupId`。

写操作须确认；`fileId` / `groupId` / `albumId` 须来自 CLI。脚本找不到时用绝对路径重试。

**转交**：搜个人云文件或图片取 `fileId` → `云盘文件管理`（搜图用 `search_image`）。发圈以 `--fileid` 为主；`--album-id` 需要的相册 ID 由 `云盘文件管理` 的整理流程（`--target album`）产出后再传入。勿把 `albumId` 填进 `--fileid`。

## CLI

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py <subcommand> [options]
python3 {baseDir}/scripts/cm_cloud_group_api.py <subcommand> -h
```

| 命令 | 说明 | 确认 |
|------|------|:----:|
| `my_join_list` | 已加入的群组（默认先查） | |
| `my_create_group_list` | 已创建的群组（加入列表未命中再查） | |
| `search_group` | 按关键词搜索 | |
| `publish_circle` | 向群组发布动态 | ✅ |

列表类命令由 CLI 自动翻完全部结果，无分页参数。按 CLI 回执向用户说明列表与发布结果。

### `my_join_list`

无业务参数。

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py my_join_list
```

### `my_create_group_list`

无业务参数。

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py my_create_group_list
```

### `search_group`

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py search_group --keywords <搜索关键字>
```

| 参数 | 必填 | 默认 | 说明 |
|------|:----:|------|------|
| `--keywords` | 是 | — | 搜索关键字；含空格时同时搜原词与去空格，按 groupId 去重合并 |

### `publish_circle`

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py publish_circle \
  --group-id <群组ID> \
  --group-name "<群组全称>" \
  --content "<正文>" \
  --fileid <fileId1,fileId2,...> \
  [--dynamic-type <0|1|2>] \
  [--file-type-list <1|2,...>]
```

相册 / 回忆故事整册发布（与 `--fileid` 二选一）：

```bash
python3 {baseDir}/scripts/cm_cloud_group_api.py publish_circle \
  --group-id <群组ID> \
  --group-name "<群组全称>" \
  --content "<正文>" \
  --album-id <albumId> \
  --album-type album
```

| 参数 | 必填 | 默认 | 说明 |
|------|:----:|------|------|
| `--group-id` | 是 | — | 目标群组 ID，来自 `my_join_list` / `my_create_group_list` / `search_group` |
| `--group-name` | 是 | — | 群组全称，取当轮 `my_join_list` / `my_create_group_list` / `search_group` 回执里该群的 `name`；搜索高亮标签可原样传入 |
| `--content` | 是 | — | 动态文字内容 |
| `--fileid` | 条件 | — | 云盘 `fileId`，英文逗号分隔，最多 500；与 `--album-id` 二选一，禁止填 `albumId` |
| `--album-id` | 条件 | — | 相册 / 回忆故事 ID，来自 `云盘文件管理` 整理流程（`--target album`）；与 `--fileid` 二选一；册内超过 500 张只发前 500 张 |
| `--album-type` | 条件 | — | 配合 `--album-id`：`album` 自定义相册 · `memory` 回忆故事 |
| `--dynamic-type` | 否 | 按附件推断 | `0` 文件 · `1` 图片 · `2` 视频。省略时：纯图→`1`，纯视频→`2`，其余（含混合、文件夹）→`0` |
| `--file-type-list` | 否 | 每条 `1` | 仅 `--fileid`：与 fileId 同序 `1` 文件 · `2` 文件夹；省略则每条按文件 |

## 用户友好提示

用户提到「圈子」时，最终回复加一句「原来的圈子功能已经升级为群组功能」。
