# 原子操作分册

> 批量上限见下「批量上限」小节。
> 本文只写各原子命令的签名与参数形态——回执字段、状态语义、下一步行动均由 stdout 回执承载，不在此重述。

所有命令形如 `python3 {baseDir}/scripts/main.py <subcommand> ...`。

## 通用约定

- `<file_ids>` 为 fileId CSV（逗号分隔）；`<file_path>` 为本地文件绝对路径。
- `<to_parent_file_id>` 为目标文件夹 fileId。
- `<dir_path>` 为云盘任意完整路径（含中间各级自动创建）。
- `<download_dir>` 为本地绝对路径，须已存在（不存在报错）。
- `batch_rename`/`batch_check_exists` 用 `fileId:newname` / `parentFileId:fileName` 对（前者 fileId+新名，后者 父目录ID+文件名），可空格分隔多个（check_exists 亦支持一项内英文逗号分隔），支持中/英文冒号。

## 命令速查

- 上传文件：`python3 {baseDir}/scripts/main.py upload <file_path> [target_dir]` — 上传本地文件到云盘指定目录（云盘路径或目录 fileId，不存在自动创建；缺省为会话默认保存目录）
- 下载文件：`python3 {baseDir}/scripts/main.py download <file_ids> <download_dir>` — 本地保存目录须已存在
- 批量移动：`python3 {baseDir}/scripts/main.py batch_move <file_ids> <to_parent_file_id>` — 源文件与目标父目录可为云盘任意有权限访问的位置
- 批量复制：`python3 {baseDir}/scripts/main.py batch_copy <file_ids> <to_parent_file_id>` — 目标父目录可为云盘任意有权限访问的位置；参数形态同 batch_move
- 创建目录：`python3 {baseDir}/scripts/main.py mkdir <dir_path>` — 云盘任意完整路径，含中间各级自动创建；同级已有去空格同名目录则复用不新建
- 重命名：`python3 {baseDir}/scripts/main.py batch_rename <fileId:newname> ...` — 一个或多个，单次最多 100 条；直接原地改名
- 创建默认保存目录：`python3 {baseDir}/scripts/main.py create_default_save_dir` — 创建或确保会话默认保存目录存在
- 查询默认保存目录：`python3 {baseDir}/scripts/main.py get_default_save_dir` — 只查询不创建
- 按 ID 查详情：`python3 {baseDir}/scripts/main.py batch_get <file_ids>` — 查文件元数据
- 播放视频/音频：`python3 {baseDir}/scripts/main.py play_media <file_id> --content-type {audio|video}` — 按 fileId 触发前端播放；batch_get 校验类型，非视频/音频或类型不匹配报错
- 查询文件路径：`python3 {baseDir}/scripts/main.py get_path <file_ids>` — 查完整云盘路径，单次最多 100 个
- 批量检查是否存在：`python3 {baseDir}/scripts/main.py batch_check_exists <parentFileId:fileName> ...` — 检查指定父目录直接子级是否存在同名；parentFileId 可传 `/` 或 `root` 表示云盘根目录

> 照片去重 / 精选由独立子命令 `refine --kind dedup|select` 承担（见 [REFINE.md](./REFINE.md)），不是原子操作。

## 批量上限

| 命令 | 上限 | 超限行为 |
|---|---|---|
| batch_move / batch_copy | 30 | 报错并提示改用「云盘文件管理」整理流程 |
| batch_rename | 100 | 报错退出 |
| get_path | 100 | 报错退出 |
| batch_get / batch_check_exists | 无条数上限 | 超 100 自动分片 |
| download | 无条数上限 | 不分片，单次请求全量获取下载地址 |

`play_media` 单条播放，不属批量上限管辖。
