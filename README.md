# 中国移动云盘 Skills 使用指南

本包是「中国移动云盘（个人云）」操作工具集，通过 HTTP 直接调用云盘 APK 的原生业务网关。

**鉴权只有一种方式：账号会话。**

```
Authorization: Basic base64("mobile:" + 账号 + ":" + token)
x-yun-api-version / x-yun-client-info / x-yun-device-id / x-yun-user-agent /
x-yun-app-channel / x-yun-net-type / x-yun-svc-type / x-yun-module-type /
x-yun-uni / x-yun-tid ...
```

会话由包内登录脚本 `common_auth/mcloud_login.py` 产出（账号密码 + 短信验证码，自动过滑块），
落到 `common_auth/session.json`。任意出口 IP 可用。

## 一、技能清单

| 技能 | 能力 | 实测命令 | 结果 |
|---|---|---|---|
| `cm_cloud_manage` 「云盘文件管理」 | 文件/图片搜索、语义搜图、图文搜人、转存搜索、上传/下载/批量移动复制/重命名/建目录/详情/路径、精选去重、整理到目录/相册/回忆故事 | `python selftest_generic_mode.py` | `RESULT: ALL PASS` |
| `cm_cloud_group_circle` 「云盘群组管理」 | 我加入/我创建的群组、关键词搜群、向群组发布动态（图片/视频/文件） | `python cm_cloud_group_circle/scripts/cm_cloud_group_api.py my_join_list` | `status=success` |
| `image_tool/ai_image_generate` 「AI生图」 | 文生图 / 图生图统一入口（改图、扩图、美颜、抠图、漫画风、画质修复、老照片修复等），异步任务 | `python image_tool/ai_image_generate/scripts/main.py --query "..." --size 2048x2048 --confirm` | 返回 `taskId`，结果归档到云盘 |
| `image_tool/image_edit_save` 「图片编辑保存」 | 裁剪 / 旋转 / 翻转后存云盘；HEIC / LIVP → JPG | `python image_tool/image_edit_save/scripts/main.py edit --image-path <本地图> --rotate 90 --confirm` | 本地处理 + 上传成功 |

## 二、快速开始

```bash
# 1) 生成 / 刷新会话（交互式：账号密码 + 手机收到的短信验证码）
python common_auth/mcloud_login.py --account <手机号> --password '<密码>' \
       --out common_auth/session.json

# 2) 确认 common_auth/.env
#    CM_CLOUD_SESSION_FILE=./common_auth/session.json
#    CM_CLOUD_APP_NAME=MClaw空间

# 3) 端到端自检（列 / 建 / 查 / 传 / 取 / 下 / 改 / 移 / 清）
python selftest_generic_mode.py        # 期望末行：RESULT: ALL PASS
```

`token` 有效期 30 天（`tokenExpire=2592000`）；过期或换账号重跑第 1 步即可。
登录细节（滑块、短信、失败码、坑位）见 `AUTH-LOGIN.md`。

## 三、目录结构

```
cloud_skills_pack_app_release/
├── README.md                       ← 本文档
├── AUTH-LOGIN.md                   ← 登录脚本与鉴权说明
├── selftest_generic_mode.py        ← 端到端自检脚本
├── selftest_generic_mode.out.txt   ← 自检原始输出
│
├── common_auth/                    ← 鉴权与会话
│   ├── mcloud_login.py             ← 登录脚本（产出 session.json）
│   ├── .env                        ← 配置（会话路径 / 应用名）
│   ├── session.json                ← 会话（真实凭据，勿外传）
│   ├── cm_cloud_auth.py            ← 鉴权头构建（会话 → Authorization + x-yun-*）
│   ├── session_folder.py           ← 会话默认目录
│   ├── cli_timing.py / cli_trace.py / operation_log.py
│
├── common/                         ← 公共库
│   ├── mclaw/api/                  ← 网关原子接口 + 联邦调度器（+ api_map.md / README.md）
│   ├── mclaw/shared/               ← 业务编排（cm_cloud / organize / postprocess / progress）
│   └── mclaw/utils/                ← 日志、设置、退出钩子
│
├── cm_cloud_manage/                ← 云盘文件管理（核心）
├── cm_cloud_group_circle/          ← 云盘群组管理
└── image_tool/                     ← 云盘图像处理工具（AI生图 + 图片编辑保存）
```

## 四、技能用法速查

### 云盘文件管理 `cm_cloud_manage`

```bash
python cm_cloud_manage/scripts/main.py -h                      # 子命令总览
python cm_cloud_manage/scripts/main.py semantic-search --query "海边日落"   # 语义搜图（一句话找图）
python cm_cloud_manage/scripts/main.py search --keyword "合同" --type doc   # 条件检索（关键词 + 过滤）
python cm_cloud_manage/scripts/main.py batch_get <fileId>      # 按 ID 查详情
python cm_cloud_manage/scripts/main.py upload <本地文件> <目标目录fileId>
python cm_cloud_manage/scripts/main.py batch_move <fileIds> <目标父目录fileId>
python cm_cloud_manage/scripts/main.py refine --from <handle> ...   # 精选 / 去重
python cm_cloud_manage/scripts/main.py organize ... --target album  # 整理到目录 / 相册 / 回忆故事
```

细节以 `cm_cloud_manage/SKILL.md` 及其 `references/` 分册为准。

### 云盘群组管理 `cm_cloud_group_circle`

```bash
python cm_cloud_group_circle/scripts/cm_cloud_group_api.py my_join_list
python cm_cloud_group_circle/scripts/cm_cloud_group_api.py my_create_group_list
python cm_cloud_group_circle/scripts/cm_cloud_group_api.py search_group --keywords <关键词>
python cm_cloud_group_circle/scripts/cm_cloud_group_api.py publish_circle --confirm ...
```

### 云盘图像处理工具 `image_tool`

```bash
# AI 生图（文生图；带 --file-id 即图生图）
python image_tool/ai_image_generate/scripts/main.py --query "<画面描述>" --size 2048x2048 --confirm
python image_tool/ai_image_generate/scripts/status.py --task-id <taskId> --wait     # 查长耗时任务

# 图片编辑保存
python image_tool/image_edit_save/scripts/main.py edit --file-id <fileId> --rotate 90 --crop-ratio 3:2 --confirm
python image_tool/image_edit_save/scripts/main.py edit --image-path <本地图> --flip horizontal --confirm
python image_tool/image_edit_save/scripts/main.py convert --input <a.heic,b.livp>   # 仅本地，转 JPG
```

写操作（上传 / 移动 / 建目录 / 发动态）须先取得用户确认。

## 五、路径权限

| 操作类型 | 路径限制 |
|---|---|
| **写入**（上传 / 移动 / 新建 / 整理落位） | 上传、移动、复制、建目录、重命名：云盘任意有权限访问的目录；整理落位固定在 `/AI空间/<CM_CLOUD_APP_NAME>` 空间内 |
| **只读**（搜索 / 浏览 / 详情 / 下载） | 无限制 |

## 六、运行前检查清单

- [ ] `common_auth/session.json` 存在（`CM_CLOUD_SESSION_FILE` 指向它）
- [ ] `common_auth/.env` 中 `CM_CLOUD_APP_NAME` 与账号空间一致
- [ ] Python 依赖：`pip install pydantic requests pycryptodome python-dotenv pillow`，
      HEIC / LIVP 转换另需 `pip install pillow-heif`
- [ ] 网络可访问 `https://personal-kd-njs.yun.139.com/`、`https://ai.yun.139.com/`、`https://group.yun.139.com/`
- [ ] 写操作前取得用户确认

## 七、自检

```bash
python selftest_generic_mode.py
# 覆盖：mkdir → batch_check_exists → get_path → upload → batch_get → download
#       → batch_rename → batch_move → 清理（移入回收站）
# 期望末行：RESULT: ALL PASS
```

原始输出见 `selftest_generic_mode.out.txt`。
