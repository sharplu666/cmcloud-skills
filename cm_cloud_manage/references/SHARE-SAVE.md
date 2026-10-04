# 分享转存（share-save / share-download）

把**别人的 139 分享链接**中的文件先转存到自己云盘（`share-save`），或转存后一步下载到本地（`share-download`）。

## 什么时候用 / 不用

- **用**：用户给了 139 分享链接（`yun.139.com/shareweb/#/w/i/…`），要把里面的文件存进自己云盘 / 下载到本地。
- **不用**：
  - 分享者是用户自己账号 → 分享里的 `contentID` 可直接 `download`（免转存）；
  - 查自己云盘里**以前转存过**的文件 → `search-transfer --transfer-type 5`（[SEARCH-TRANSFER.md](./SEARCH-TRANSFER.md)）；
  - 非 139 的分享链接（百度/阿里/夸克等）→ 本技能不支持。

## 执行命令

```bash
# 转存到自己云盘
python3 {baseDir}/scripts/main.py share-save "<分享链接或分享ID>" \
  [--passwd "<提取码>"] [--target-dir "<云盘目录>"]

# 转存 + 下载到本地（一步完成）
python3 {baseDir}/scripts/main.py share-download "<分享链接或分享ID>" <本地目录> \
  [--passwd "<提取码>"] [--target-dir "<云盘目录>"]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `share` | 是 | 139 分享链接；可直接粘贴整段分享文本（自动识别其中的 `提取码:xxxx`），或只传分享 ID（`/w/i/` 后面那串） |
| `--passwd` | 否 | 提取码；不传时从分享文本中自动识别，识别不到则按无密码分享处理 |
| `--target-dir` | 否 | 转存目标云盘目录：云盘路径（不存在自动创建）或目录 fileId；缺省为当前会话默认保存目录 |
| `download_dir`（share-download） | 是 | 本地保存目录的绝对路径，须已存在；按分享内的目录结构存放 |

## 行为说明

1. **解析**：从输入中提取分享 ID 与提取码，调用分享 V6 接口递归列出分享内全部文件/文件夹。
2. **直连快路径**：若分享者就是当前登录账号，文件本就在自己云盘中，跳过转存直接取用（回执 `mode=direct`）。
3. **转存**（写操作，他人分享时）：提交转存任务到目标目录；顶层文件夹整体转存（服务端自动重建目录结构）。转存是服务端异步任务，命令内轮询等待落盘（最长 600 秒）。
3. **状态口径**：每个顶层项标记为 `saved`（本次新转存）/ `existed`（目标目录下已存在同名，未重复转存）/ `pending`（任务已提交但轮询超时仍未确认落盘；服务端任务仍在执行，可稍后用 `batch_check_exists <目标目录fileId>:<名称>` 复查）。
4. **下载**（share-download）：按分享内的相对目录结构下载到本地。

## 回执

- `share-save`：meta（含 `shareName` / `targetDir` / `taskId` / `savedCount` / `existedCount` / `pendingCount`）+ 逐项 result（含转存后的云盘 `fileId` 与 `cloudPath`）。
- `share-download`：先出转存阶段 meta（`phase=save`），再出下载阶段 meta（`phase=download`）+ 逐文件 result（含 `relPath` / `localPath`）。
- 转存后的文件保留在用户云盘中（本技能不支持删除），`share-download` 不会自动清理云盘副本。

## 常见错误

| 现象 | 含义 / 处理 |
|------|-------------|
| `无法从输入中解析出分享 ID` | 输入不是 139 分享链接；检查链接是否完整 |
| `[200000727]` | 分享链接不存在或已被分享者取消（无需重试） |
| `[200000401]` | 分享链接已过期（无需重试） |
| `[200000402]` | 分享链接已达访问次数上限（无需重试） |
| 提示带提取码相关 | 分享设有提取码但未提供/错误 → 用 `--passwd` 传入 |
| `pendingCount > 0` | 部分文件 600 秒内未确认落盘；转存任务仍在服务端执行，稍后用 `batch_check_exists` 确认 |

## 完整例子

```bash
# 用户粘贴了整段分享文本（含提取码），转存到默认目录
python3 {baseDir}/scripts/main.py share-save "https://yun.139.com/shareweb/#/w/i/2xTrL8mjuKZ1l 提取码:fwaw"

# 转存到指定云盘目录
python3 {baseDir}/scripts/main.py share-save "2xTrL8mjuKZ1l" --passwd fwaw --target-dir "/AI空间/MClaw空间/分享"

# 转存并下载到本地
python3 {baseDir}/scripts/main.py share-download "https://yun.139.com/shareweb/#/w/i/2xTrLNpeA3J59" /tmp/dl
```
