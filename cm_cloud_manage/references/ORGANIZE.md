# 整理（organize）

一个命令四段流程，`--step` 区分（plan → submit → status / retry），搜索流程获取的
handle 全程串联。`--target` 决定整理成什么：**recommend**（用户没说方向时先出推荐
）/ **drive** 个人云目录 / **album** 相册 / **memory** 回忆故事。去重 / 精选统一走
[refine](./REFINE.md)，organize 只做落位。

## 前置输入

整理以落盘语料 `<handle>/<file>.jsonl` 为输入（`--from`），本 md 只覆盖整理：

- 还没有 `<handle>`（用户要整理但没搜过）→ 先执行搜索能力，按 SKILL.md「搜索能力」路由选命令
- 需要对语料精选/去重/合并后再整理 → 见 [REFINE.md](./REFINE.md)

## plan - 生成整理方案

```
python3 {baseDir}/scripts/main.py organize --step plan --from <handle>/<file>.jsonl --target <recommend|drive|album|memory> [参数]
```

**必填**：

- `--from <handle>/<file>.jsonl`
- `--target recommend|drive|album|memory`：整理去向判定。
  - `recommend`：用户没有说明整理去向，给用户主动推荐——显式传 recommend 先出推荐。示例：搜xx，整理一下。
  - `drive`：整理到/放到/归档到目录/文件夹。
  - `album`：做成相册/整理成相册/整理到相册/放到相簿。
  - `memory`：整理到回忆故事/回忆相册/生成回忆。

**可选**：
- `--bucket <维度>`：分组维度，可逗号隔开传多个（如 `year,fileExtension`）。
- `--mode cross|hierarchical`：单维度无需传入，多个维度可以选择整理结果的结构。
  - `cross`：拼成一层「年_类型」
  - `hierarchical`：嵌套「年/类型」目录（相册无嵌套，自动拍平成「年_类型」）
- `--merge-into <名>`：不管分了多少组，全部合成一个——drive = 一个平铺文件夹，album = 一个册子（图片全量）；memory = 一个回忆故事。
  - 与 `--parent-path` 同用时（仅 drive），最终保存目录为`parent-path`的`merge-into`文件夹下
- `--only <bucketId>`：只保留上一轮 `--step plan`预览里对应 `<bucketId>` 的组（如 `1,3`）——对整理方案按条件收窄时用它替代重新搜索。
  - bucketId 看 plan 回执 renderText 每行的 `<bucketId>`（形如「<bucketId>1</bucketId> <bucketName>jpg</bucketName>：5 个文件」；recommend 三情形桶行同样带）
  - bucketId 从 1 开始，聚类时冻结、跨 target 稳定——同输入同维度下 drive / album / memory 编号一致，可直接跨 target 引用
  - memory 精选清空的桶显示「精选后为空」且编号不回收（命中它会报错）
  - 换了`bucket`分组维度要重新看 bucketId
- `--unknown keep|drop`：识别不出维度值的文件（如没有拍摄时间的「未知月份」）怎么处理。默认为`keep`。

**仅 drive**（传给其他 target 会直接报错，并提示怎么改）：

- `--parent-path <路径>`：整理目标父目录（仅 plan + drive）
  - 用户没有指定，无需传入，会默认使用云盘中固定的默认目录。
  - 如果用户只提了目标父目录名称，则传入相对路径，该路径会拼接到默认目录后使用；
  - 如果用户指定了目标父目录的绝对路径，则直接传入该路径，但是该路径须在`/AI空间/MClaw空间` 下；
- `--rename-template <模板>`：把桶内文件按一个固定格式重命名。
  - 模板是一段可以带占位符的字符串，占位符分两类：基础占位符 4 个 + 任意已注册维度占位符：
    - `{bucket}`: 桶名整串，默认取`--bucket`的值。
    - `{index}`: 桶内序号（1 起，补零 3 位，如 001）。
    - `{name}`: 原文件名去掉扩展名。
    - `{ext}`: 原扩展名（不带点）。
    - 维度占位符：任意已注册维度名，如`{month}`、`{city}`，渲染为该文件的维度值，未传入的维度渲染为空串。
  - 示例见 [examples.md](./examples.md) 示例 8。

### bucket 全集

未列出的桶名直接报错。 精选过滤、整理均用这套维度。

**时间维度**：

- 默认系列 → `--bucket day|week|month|year`（**月为默认粒度**），有分级降级——拍摄时间缺失时降级取本地创建时间，再缺失降级取上传时间
- 拍摄时间 → `--bucket takenDay|takenWeek|takenMonth|takenYear`
- 上传时间 → `--bucket uploadDay|uploadWeek|uploadMonth|uploadYear`
- 更新时间 → `--bucket updateDay|updateWeek|updateMonth|updateYear`
- **注意**: 如果搜索按上传/拍摄时间搜索，则应该使用上传/拍摄时间的整理维度
- **粒度**：`Day` 最细（具体到某一天），`Week` / `Month` / `Year` 依次变粗；渲染值示例——`day`/`takenDay` → `2026-05-18`，`month`/`takenMonth` → `2026-05`，`year`/`takenYear` → `2026`

**地点维度**：

- 地点（国家） → `--bucket country`
- 地点（省份） → `--bucket province`
- 地点（城市） → `--bucket city`（**地点维度默认粒度**；`location` 等价于 `city`）
- 地点（区县） → `--bucket district`
- 地点（乡镇/街道） → `--bucket township`
- 地点（具体位置/景点） → `--bucket locationAoi`（一张图片可能命中多个景点）

**人物/事物标签维度**（一张图片可能命中多个人物/事物标签）：

- 人名 → `--bucket peopleNameList`
- 关系 → `--bucket relationshipNameList`（本人，伴侣，孩子，爸爸，妈妈，亲属，朋友，同事，其他等；一张图片可能同时含多个关系，如孩子、伴侣）
- 事物标签 → `--bucket thingLabelList`（枚举值：猫，狗，动物，美食，花，树，植物，建筑，饮品，天空，日出、日落，河流、湖泊，海洋，沙漠，雪景，草地，夜景，交通工具，运动，聚会，截图，文档，证件，其他证件，身份证，银行卡，社保卡，港澳通行证，驾驶证，行驶证，护照，居住证，学生证，户口本，房产证，营业执照；一张图片可能同时命中多个标签，如猫、狗）
- 地标/名人 → `--bucket objectList`

**文件属性维度**：

- 文件分类 → `--bucket category`（取值如 `image`/`video`/`doc`）
- 扩展名 → `--bucket fileExtension`（小写，如 `jpg`/`mp4`/`pdf`）
- 人脸数量 → `--bucket faceCount`（桶 key 为 `1人照`/`2人照`/`3人照`...；仅图片）
- 单人照/双人照/多人照 → `--bucket faceGroup`（桶 key 为 `未知类型`/`单人照`/`双人照`/`多人照`；仅图片；0 人脸归 `未知类型`）

多维组合：`--bucket A,B` 嵌套 `A/B` 目录；`--mode cross --bucket A,B` 一层 `A_B`。

默认粒度（用户未指定时）：「按时间」→ `--bucket month`；「按地点」→ `--bucket city`；「按时间+地点」→ `--mode hierarchical --bucket month,city`。时间口径跟随这批文件的时间维度：用户按上传时间搜/描述的，「按月/周/日」用 `upload*` 系列；按拍摄时间搜/描述的用默认系列或 `taken*`。判断不了口径，先问用户再动手。

## submit - 提交 plan 快照

```
python3 {baseDir}/scripts/main.py organize --step submit --from <handle>/plan.jsonl --processing-hint "…" [--dry-run]
```

用户同意 plan 预览后才提交。任务小的话提交回执会**直接出结果**（全部成功 / 全部失败 / 部分成功），无需再查 status；回执是「整理任务已提交！」等待文案才是异步任务。回执 `data.target` 记住整理去向，retry 时要用。

- `--from <handle>/plan.jsonl`：plan 产出的方案快照（必填）
- `--processing-hint`：必填，≤250 字符，超长截断
- `--dry-run`：仅校验，不提交

## status - 查任务进度

异步完成后服务端推送含 `taskId` 的 `<System-Event>`。需要用status命令来查询真实的任务完成情况。

正确示例：
```
python3 {baseDir}/scripts/main.py organize --step status --task-id <id>
```

**错误示例**： 不通过 `status` 查询结果，直接告知用户 `整理完成`。

## retry - 对失败任务重试

如果查询异步任务结果后，如果任务失败，如果用户要求重试任务，可以用retry命令：
```
python3 {baseDir}/scripts/main.py organize --step retry --task-id <id> --target <drive|album|memory>
```

- `--target`：必填，取 submit 回执 `data.target`（整理去向），用于任务卡与文案。

## 常见问题和安全限制

### 计划生成相册 / 回忆故事

相册 / 回忆故事仅支持图片：计划（`plan`）会自动过滤非图片文件（视频、文档等），回执会说明过滤数量；语料全是非图片时直接报错。回忆故事还会对图片去重精选，精选失败直接告知用户即可。

### 用户资产安全确认

整理涉及用户资产变更，在生成计划后需要用户确认才能提交整理任务。

### 整理任务相关提醒

整理需要时间，提交任务后在用户没有要求的情况下，不需要主动轮询。
提交任务失败直接告知用户即可，将决策权交给用户，避免用户资产变更不符合预期的情况。

更多组合用例（精选 + 整理、合并塌平、多维嵌套、相册 / 回忆故事）见 [examples.md](./examples.md)。
