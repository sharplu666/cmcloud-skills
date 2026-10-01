---
name: 图片编辑保存
description: >
  图片裁剪/旋转/翻转后保存到中国移动云盘，以及 HEIC/LIVP 转 JPG 格式转换。
  触发场景：用户要求裁剪/裁切/截取/旋转/翻转/转正图片、调整图片比例（如 3:2、16:9）
  并将结果保存到云盘默认文件夹或指定目录；或要求把 HEIC/LIVP（实况照片）转成 JPG。
---

# 图片编辑保存

两场景分发入口：图片几何编辑（edit）、HEIC/LIVP 转 JPG（convert）。

## 场景路由

### 图片编辑（edit）

裁剪、旋转、翻转、调整比例，结果作为**新文件**上传云盘，原文件不动。

- **输入**：云盘图片传 fileId；本地图片传路径（二选一）
- **操作**：`--rotate` / `--flip` / `--crop-ratio` 至少一项，可组合；处理顺序固定为旋转 → 翻转 → 裁剪
- **输入格式**：常见图片 + HEIC + LIVP（自动解包取静止帧）；HEIC/LIVP 输入的结果输出 `.jpg`，其余保持原格式
- **例子**：顺时针旋转90度、转正这张照片、左右镜像一下、裁成16:9、先旋转90度再调3:2

#### 执行命令

```bash
python3 {baseDir}/image_edit_save/scripts/main.py edit \
  --file-id "<输入图fileId>" \
  --rotate 90 \
  --crop-ratio 3:2 \
  --save-dir-id "<目录fileId>" \
  --confirm
```

本地图片改用 `--image-path "<本地路径>"`（与 `--file-id` 互斥）。

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--file-id` / `--image-path` | 二选一 | — | 输入图云盘 fileId / 本地路径（须真实存在） |
| `--rotate` | 操作三选一 | — | 顺时针角度，如 `90` / `180` / `270`，支持自定义角度 |
| `--flip` | ↑ | — | `horizontal` 左右镜像 / `vertical` 上下翻转 |
| `--crop-ratio` | ↑ | — | 居中裁剪到宽高比，如 `3:2`、`16:9`（保留最大画面，比例一致时不裁） |
| `--save-dir-id` | 否 | 会话默认文件夹 | 另存目录的 fileId |
| `--confirm` | 否 | 仅预览 | 不加仅打印处理计划，不触碰云盘 |

**保存路径解析**：用户提到保存路径时，先由「云盘文件管理」技能把路径解析为 fileId 再传 `--save-dir-id`（合法路径以 `/AI空间/MClaw空间` 开头；不唯一时列出供用户选择，禁止自行决策）；**不要直接向用户要 fileId**。用户未指定路径时省略该参数。

### HEIC / LIVP 转 JPG（convert）

只能本地：输入收本地路径，输出仅保存到本地固定目录，**不支持上传云盘、不支持自定义输出目录**。适用「模型接口不吃 HEIC」「实况照片取静止帧」。

- **输入**：本地 HEIC/LIVP 绝对路径，1-10 个（按文件内容判定，jpg/png 等常见图报错「无需转换」）
- **输出**：仅本地目录 `~/.openclaw/workspace/imageConvertJpg/image_<YYYYMMDDHHMMSS>.jpg`，同名不覆盖
- **例子**：把这张 heic 转成 jpg、实况照片转普通图片

#### 执行命令

```bash
python3 {baseDir}/image_edit_save/scripts/main.py convert --input "<绝对路径1>,<绝对路径2>"
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--input` | 是 | 本地绝对路径 CSV（英文逗号分隔），1-10 个 |

云盘里的 HEIC/LIVP 需先用下载到本地再传入；本命令不接受 fileId。

## 下游交接

- convert 的输出路径在回执中，可直接作为 `edit --image-path` 或 AI 生图的本地图片输入。

## 易混点

- **几何编辑 vs AI 改图**：画面内容理解/生成/消除/风格化（加文字、去路人、美颜、扩图等）→ `../ai_image_generate/index.md`；只有几何变换（裁剪/旋转/翻转/调比例）走本技能。
- **convert vs edit**：只要格式转换、无几何操作 → `convert`（只收本地路径）；HEIC/LIVP 要直接编辑 → `edit`（内部同样解包/解码）。
- **仅搜索/整理图片**（无编辑意图）→ 转交「云盘文件管理」。
- **图片配文**（图片进、文字出）→ 按 AI 生图 `index.md`「能力边界 · 特殊路径」处理。
