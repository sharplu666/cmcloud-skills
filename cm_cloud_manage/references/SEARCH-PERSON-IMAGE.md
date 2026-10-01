# 图文搜人（person-search）

用「参考图 + 一句自然语言」在云盘图库里找某人 / 某些人的照片。

## 什么时候用 / 不用

- **用**：query 要找的目标中出现「人」，且至少一人有锚点——本轮指定的参考图或上下文绑定过要搜索的人物的`<fileid>`参考图。**隐式指认即锚点**：本轮选中文件 + query 中人物指代（这个人/她/他们/图中的X）即视为锚点成立，直接执行，禁止向用户追问人物身份。**附带时间/地点/场景条件（如「她2024年5月拍的照片」「他在苏州的照片」）不改变路由**，仍走图文搜人，条件留在 query 文字里。
- **不用**：找人但无任何锚点，或参考图不含人 → 改用 `references/SEARCH-FILE.md` 语义搜图。
- **子命令与参数以本文档为准**：图文搜人只有 `person-search` 一个子命令，参数只有 `--file-ids`/`--query`/`--bindings`（二次澄清时 `--select-faces`/`--from`）；

## query 透传规则

query 的最终视觉锚定改写由脚本内部的多模态模型完成，**你不做改写、不建槽位、不翻译称呼**。你只做三件事：**选锚点图、抄请求原话、抄绑定原话**。

- **--query**：用户请求**原话透传**，规则分三类：
  - **仅可删除**：语气词、请求词（帮我/麻烦）、搜索动作词（找/搜/看看）——此外一个字都不动。
  - **实质内容禁止删除、禁止同义替换、禁止翻译**：人物称呼（我老婆/她/这个人，不得译成"图中的人物"）、其他人名、时间词（去年/2024年5月）、地点、数量/范围词（所有/全部/其他）、照片类型词（单人照/合照/生日照）、属性过滤词（不要男生的，不得改写为"女性"）。
  - **唯一例外——澄清合并**：需要澄清后用户补充了描述时，把描述并进原 query、合成新的完整 query 透传。

## 图文搜人通用流程

只有两种命令。**是否需要澄清由 Python 回执判定，不要自行推断**，判别依据
- 需要澄清：看末尾 `record=handle` 行的 `params.ambiguity`——`true` 时返回 `:::selectFaceList` 卡，需要用户选脸（该 handle 即下轮 `--from`）；
- 无需澄清，脚本直接搜索：`params.ambiguity`——`false`。

### ① 首次请求

```bash
python3 {baseDir}/scripts/main.py person-search \
  --file-ids <fileId1>,<fileId2>,... \
  --query "<用户请求原话，见query透传规则>" \
  --bindings "<img1>指认原话</img1><img2>指认原话</img2>"
```

- **query**: 必填，用户请求原话，见query透传规则。
- **--file-ids**：必填，**本轮 query 涉及人物**的锚点图全集：本轮上传/指定的图 + 历史绑定过**这些人**的图，取并集全传（漏传任何一张 = 该人物无法定位）；**与本轮搜索无关的历史绑定图不传**（只传本轮需要的参考图）。顺序按用户提及先后，本轮上传的图在前。
- **--bindings**：选填，（`--file-ids` 首搜必传）：**人物指称与图的对应关系**，用 XML 标签逐条包裹：`<imgN>指称原话</imgN>`，其中 **N 是该图在 `--file-ids` 中的次序**（第 1 个 fileId 对应 `<img1>`，第 2 个对应 `<img2>`…）
  - **imgN 必须与本轮 `--file-ids` 一一对应且个数一致。
  - bindings 只描述本轮实际传入的图，未传入之图的人物指称不写**。必须包含两类：①历史上用户"指认图中人是谁"的原话（"这是我老婆""左边的是晓彤"）；②**query 中指代参考图人物的指称**（图中的女生/这个人/红头发这个人/这两个人…）——逐条声明该指称锚定哪张图，**没有此对应关系无从得知哪个人物是图中参考人物，哪个人物不是图中人物**。
  - 与参考图无关的人物指称（如"其他人物"）不进 bindings。例如用户指定一张图并告知"这是某人"，query 同时搜这个人和一个与参考图无关的人 → bindings 只写 `<img1>某人</img1>` 一条 。
  - **只抄原话，不解析、不翻译、不总结**。

### ② 需要澄清时

卡片文字会引导用户**描述要找的人**（位置/衣着，如"最左边那位""穿黑色上衣的男生"）。
收到用户的描述后，**首选：用澄清后的完整 query 请求**。

若前端回传了选脸消息（形如 `User has selected the following faces from the face selection card... selectedFaces:<selectedFaces>...`），走选脸二次：

```bash
python3 {baseDir}/scripts/main.py person-search \
  --select-faces '<selectedFaces>' \
  --from op_<6位编码>/ambiguity.jsonl \
  [--query "<澄清后的完整 query>"]
```

- `--query`：选填，澄清后的完整 query，用户只选脸不澄清时无需传入。
- `--select-faces`：必填，用户回传的人脸信息（**`index` 原样透传，别改坐标别重排**；坐标为**原样透传即可，勿自行换算或构造**）。**必须与 `--from` 同传**；和首次请求的 `--file-ids` 互斥。
- `--from`：必填，需要澄清时的`<handle>`（形如 `op_<6位编码>/ambiguity.jsonl`）。
- 用户明确说"不是这个人/换一个"：重新走首次请求（同 fileId、原 query 不变）。

## 完整例子

### 例1：单图搜人，无指认语句

用户指定参考图并且直接搜索："帮我找这个人的照片"

```bash
python3 {baseDir}/scripts/main.py person-search \
  --file-ids <fileId> \
  --query "这个人的照片" \
  --bindings "<img1>这个人的照片</img1>"
```

### 例2：多轮对话，带指认与附加条件

第一轮对话：用户指定参考图并且说明："这是我老婆"
第N轮用户对话："搜我老婆和刘德华的合照"

```bash
python3 {baseDir}/scripts/main.py person-search \
  --file-ids <fileId> \
  --query "我老婆和刘德华的合照" \
  --bindings "<img1>这是我老婆</img1>"
```

### 例3：需要澄清，两轮。

用户上传三人合影："帮我找第一个人的照片"

首搜（同例1形式，query 原话透传），`person-search` 返回 `:::selectFaceList` 代表需要澄清。

澄清时，假如能明晰候选人数（`N`），需要使用以下用户**用户友好提示**：
```text
<sayToUser>：
- 1、只找这N个人的合照（必须同框）
- 2、包含这N个人（一起或单独出现都可以）
- 3、只找其中某一个人的照片
```

#### 用户没有选择人脸

假如用户没有选择人脸，而是直接回复"最左边扎马尾的那个"。此时，agent应该再次尝试根据query和bindings尝试匹配人脸。

```bash
python3 {baseDir}/scripts/main.py person-search \
  --file-ids <fileId> \
  --query "最左边扎马尾的那个人的照片" \
  --bindings "<img1>最左边扎马尾的那个</img1>"
```

#### 用户选择人脸并且添加搜索语句

用户选择人脸，并且回复"最左边扎马尾的那个"。此时，`select-faces` 使用 `<selectedFaces>`，并且透传澄清后的完整 query。

```bash
python3 {baseDir}/scripts/main.py person-search \
  --query "最左边扎马尾的那个人的照片" \
  --select-faces '<selectedFaces>' \
  --from op_<6位编码>/ambiguity.jsonl
 ```

#### 用户选择人脸但没有补充搜索语句

用户选择人脸，没有补充搜索语句。此时，`select-faces` 使用 `<selectedFaces>`。

```bash
python3 {baseDir}/scripts/main.py person-search \
  --select-faces '<selectedFaces>' \
  --from op_<6位编码>/ambiguity.jsonl
 ```

## 下游交接

当搜索结果非空时，返回 `<handle>`（`op_<6位编码>/search.jsonl`），记下 handle 交给下游命令；使用搜索结果的下游能力路由：
- 精选、去重、合并多份搜索结果。见 `references/REFINE.md`
- 搜索结果按类别整理到个人云文件夹/相册/回忆故事。见 `references/ORGANIZE.md`
