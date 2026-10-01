# 如何在 api 中新增一个 API

> **重要规则**：编辑本文档时，必须以精简可复用的项目级经验写入，禁止给出不必要的/特定示例。文档保持精简整洁。
>
> **强制规则**：任一步骤缺失即拒绝合并。

## 核心原则（先读）

1. **没有接口文档，禁止动手写代码** — 文档是字段、PATH、同步/异步判定的唯一依据
2. **测试禁止编造数据** — 请求参数与响应 JSON 必须来自真实抓包（用户提供）；未提供时**先问再写**；每个枚举分支单独覆盖
3. **测试不放进 `api/` package** — 统一放 `common/tests/<skill>/`，避免 pytest 进运行时依赖
4. **`status_log` 仅写日志文件，大模型无法感知** — 需要让大模型在上下文工程中感知到的关键信息（任务进度、状态变化、关键结果、错误原因等）必须用 `print()` 输出到 stdout；`logger.status_log` 只落盘，不会进入对话上下文
5. **每个接口都定义自己的入参/出参 BaseModel（pydantic），API 子类必须类型化方法签名** — `execute(request)` 的入参指向本接口的 Request 子类，返回值指向 Response 子类；仅当字段与基类**完全一致**时才跳过（直接沿用基类类型）。出参按响应数据结构判定是否重写 `from_response`（见步骤 3）；异步接口扩展字段通过重写 `_build_result` 钩子注入（见步骤 4）
6. **可调参数禁止散落字面量** — 超时、轮询间隔、目录根、URL 前缀、阈值等可调参数集中到 `utils/settings.py` 的 `AllSetting` 子类：跨 skill 共享的加进 `ProjectSettings` / `AuthEnvSettings`，仅本 skill 用的在 `api/<skill_name>/` 下定义独立 `AllSetting` 子类。API 子类、测试、脚本统一 `from mclaw.utils.settings import XxxSetting` 后用 `XxxSetting.FIELD` 引用，**禁止在业务代码硬编码数字 / 路径 / URL 字面量**
7. **`api/base/` 是全局根基类，非必要不动** — `_base_api.py` / `_http.py` / `base_sync_api.py` / `base_async_api.py` 被所有已注册接口继承，任何改动波及全部 skill。新增 API 时优先通过继承、组合、钩子（`_build_result` 等）在子类内扩展，不要回头改基类。若确需修改基类（修 bug、扩契约、改 HTTP 行为），**必须先显式告知用户这是全局影响**，列出受影响的 registry 与接口清单，征得确认后再动手；改动后须重跑 `common/tests/` 下各 skill 的集成测试回归

## 总流程

```
接口文档 → 选/建子技能文件夹 → 入参/出参 BaseModel → API 子类并注册 → pytest → 登记 api_map
```

## 步骤 1：接口文档（强制前置）

确认：接口路径、请求方法、同步/异步、入参字段（名/类型/必填）、出参字段、错误码、异步的 `status` 终态语义。

没有文档时**明确要求用户提供**，不要猜测。参考位置：`references/api.md`、`dev/docs/api/`、`dev/server/api_server.py`。

## 步骤 2：子技能文件夹

**路径**：`api/<skill_name>/<api_name>_api.py`（一个 `.py` 一个 API）。生产代码与测试分离：

```
api/<skill_name>/              tests/<skill_name>/
├── __init__.py                       ├── __init__.py
└── <api_name>_api.py                 └── test_<api_name>_api.py
```

注册链接入（联邦式 Service，三处）：

```python
# 1) api/<skill_name>/__init__.py —— 创建自治 registry + 导入即注册
from mclaw.api.registry import ApiRegistry

< skill_name > _api_registry = ApiRegistry(name='<skill_name>')

from . import xxx_api  # noqa: F401  副作用：注册到本 registry

__all__ = ['<skill_name>_api_registry']

# 2) api/__init__.py 末尾 —— 触发整个子包的注册链
from . import < skill_name >

# 3) api/dispatcher.py 的 ApiDispatcher.__init__ —— 联邦进顶层调度器
from mclaw.api. < skill_name >
import < skill_name > _api_registry
self._mount('<skill_name>', < skill_name > _api_registry)
```

> `dev/skills/search_fusion/`（独立 skill 包，历史遗留 CLI）与 `api/search_fusion/`（registry 模式）不是同一个东西，新增走后者。

## 步骤 3：入参/出参 BaseModel（pydantic）

| | 同步 | 异步 |
|--|------|------|
| 入参基类 | `SyncRequest` | `AsyncSubmitRequest` |
| 出参基类 | `SyncResponse` | `AsyncPollResponse` |

> **仅当字段与基类一致才继承基类**。基类（如 `AsyncSubmitRequest`）含 `sendType` / `fileUrl` / `fileId` 等媒体发送字段，cloudId 体系或其他非媒体接口继承它会引入无关字段污染。字段不匹配时，入参直接继承 `pydantic.BaseModel`，但异步接口需自带 `poll_interval` / `poll_max_attempts`（`exclude=True`）供 `BaseAsyncApi._poll` 使用。

入参必须实现 `to_payload()`，**字段名按接口文档原样（驼峰）**，用 `Field(alias='驼峰名')` 声明：

```python
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field
from mclaw.api import SyncRequest


class FaceDetectRequest(SyncRequest):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    detect_mode: int = Field(0, alias='detectMode')

    def to_payload(self) -> Dict[str, Any]:
        # 基类 to_payload 做 model_dump(by_alias=True, exclude_none=True)
        # 已能输出大部分字段；仅当需要条件字段（按 sendType 选 fileUrl/fileId）
        # 或自定义 wrapper 结构时才重写。
        p = super().to_payload()
        p['detectMode'] = self.detect_mode
        return p
```

### 可选字段用 `Optional + None`，禁止空串/0 占位

响应中「非必须」「仅在某条件下返回」的字段必须用 `Optional[T] = Field(None, alias='...')`，**不要用 `''` / `0` / `False` 占位**。`None` 表达「未返回」，空串/0 是合法业务值，占位会混淆二者；配合 `to_payload(exclude_none=True)` 也不会被误发送。必填字段仍用 `Field(..., alias='...')`。

### 出参 `from_response` 重写判定（按响应数据结构决定，一般都要重写）

出参基类提供默认 `from_response()`，行为因基类而异：

| 基类 | 默认 `from_response` 行为 | 适用场景 |
|------|------------------------|---------|
| `SyncResponse` | **展平 `data` 嵌套层**——`{success, code, data: {bizField}}` 中 `data` 内字段提升到顶层后 `model_validate` | 业务字段直接位于 `data` 下，无派生计算 |
| `AsyncSubmitResponse` | **展平 `data` 嵌套层**——提取 `taskId`/`queueOffset` | 提交响应业务字段在 `data` 下 |
| `AsyncPollResponse` | **定向提取**——从 `data` 取 `status`/`resultList`/`taskId` 后手动构造（非展平） | 默认字段集，无扩展 |

**重写判定规则**：取决于本接口响应数据结构与基类是否一致。

- **结构与基类一致**（字段集相同、嵌套层级相同）：跳过重写，直接继承
- **结构不同**（业务字段不在 `data` 下、字段名不同、需要派生计算、Response 子类扩展了基类没有的字段）：**必须重写 `from_response`**

> 实际中接口响应字段往往与基类**不完全一致**（扩展业务字段、字段命名差异、嵌套层级不同），故**一般都需要重写 `from_response`** 定制解析逻辑。仅当响应字段与基类**完全一致**时才跳过。

- 同步接口扩展 Response 字段时：重写 `_parse_response` 钩子指向本接口的 Response 子类（基类 `BaseSyncApi._parse_response` 硬编码用 `SyncResponse.from_response`，识别不了子类）
- 异步接口扩展 Response 字段时：重写 `_build_result` 钩子从 `raw` 提取扩展字段并构造子类响应（基类 `_poll` 硬编码用 `AsyncPollResponse.from_response`）

异步最终结果默认用 `AsyncPollResponse`（已封装 `status`/`file_url_list`/`is_success`），有额外字段再继承扩展。

## 步骤 4：API 子类并注册

同步继承 `BaseSyncApi`，异步继承 `BaseAsyncApi`，XML 信封接口继承 `BaseXmlSyncApi`（Request 实现 `to_xml()`）。同步/异步由 registry 通过 `issubclass` 自动判定，**无需声明 `api_kind`**；XML 计为 sync。

```python
from mclaw.api. < skill_name >
import < skill_name > _api_registry


@

< skill_name > _api_registry.register('face_detect')


class FaceDetectApi(BaseSyncApi):
    PATH = '/richlifeApp/aiService/api/image/detect/face'  # 必填
    api_category = 'detect'  # 可选
    api_label = '人脸检测'  # 可选


@

< skill_name > _api_registry.register('text_to_image')


class TextToImageApi(BaseAsyncApi):
    SUBMIT_PATH = '/richlifeApp/aiService/api/image/textToImage'  # 必填
    POLL_PATH = '/richlifeApp/aiService/api/async/task/result'  # 可选
```

### 同步 vs 异步判定

| 信号 | 同步 | 异步 |
|------|------|------|
| 文档返回 | 直接业务结果 | `taskId` + `queueOffset` |
| 需轮询 | 否 | 是 |
| PATH | `PATH` | `SUBMIT_PATH` + `POLL_PATH` |

> 项目 17 个 AI 图片能力里，仅 `ai_portrait_face_detect` 是同步，其余 16 个异步。

### 注册名与调用

`@<skill_name>_api_registry.register('leaf_name')` 的 leaf_name 在本子包 registry 内唯一（重复抛 `ValueError`），蛇形小写，不可含 `.`。注册后通过 `ApiDispatcher` 双入口调用，**不需要 import 具体子类**：

```python
from mclaw.api import ApiDispatcher

d = ApiDispatcher(host=HOST, auth_fn=get_auth_header)

# 双入口等价
resp = d. < skill_name >.leaf_name(req)  # 属性链（一级命名空间是真实属性）
resp = d.execute('<skill_name>.leaf_name', req)  # dotted 字符串（可 grep、可动态派发）
```

### 类型化 execute 签名（强制）

基类 `execute` 是泛化的 `AsyncSubmitRequest -> AsyncPollResponse`（同步 `SyncRequest -> SyncResponse`）。**入参/出参与基类不一致时必须**：

1. 重写 `execute` 签名：入参指向本接口 Request 子类，返回值指向 Response 子类（用 `super().execute` 转发）
2. 异步接口重写 `_build_result` 钩子：基类 `_poll` 硬编码 `AsyncPollResponse.from_response`，识别不了子类扩展字段，需在钩子里从 `raw` 提取并构造子类响应

> 仅当本接口 Request/Response 字段与基类**完全一致**（无扩展字段、无字段差异）时才跳过。
> 参考实现：`api/operation/batch_move_files_api.py`。

## 步骤 5：pytest 测试（强制）

**位置**：`common/tests/<skill_name>/test_<api_name>_api.py`

**方式**：集成测试，**不 mock 响应**。通过 `common/tests/conftest.py` 的 `api_client` fixture（真实 HOST + `api.auth.get_auth_header`）发起真实 HTTP；鉴权不可用时整模块自动 skip。

**运行**：

```bash
cd dev/skills/common
python -m pytest tests/<skill_name>/ -v
```

### 测试约定

- **入参抽到模块顶部常量**：按业务可调，避免散落在用例内
- **每个枚举分支一个测试**：如 `searchType` 的每个值、`send_type=1 vs 3`，**不要合并**
- **时间范围动态计算**：`datetime.now() - timedelta(days=365)`，不要硬编码日期
- **必填字段无业务值时传空串**：如 `keyword=''` 表示不限关键字，不要省略
- **依赖智能分析的字段（`thingList` / `addressList`）必须同时设 `enable_intelligent=True` + `intelligent_type`**，否则服务端返回参数错误
- **断言只看结构**：`success` / `code` / `file_list` 类型 + 字段类型，**不硬编码具体业务值**（依赖账户实际数据）
- **禁止 mock 响应数据**：响应来自服务端，不要自造 `_SUCCESS_RESPONSE` 之类的常量

## 步骤 6：登记到 api_map

新增 API 后**必须**同步追加一行到 `api/api_map.md`，记录三项：**dotted registry 名**（`<skill_name>.<leaf>`）、接口路径（含方法）、调用脚本相对路径。

## 检查清单

- [ ] 接口文档已确认
- [ ] 子技能文件夹位置正确：`api/<skill_name>/<api_name>_api.py`
- [ ] 两处 `__init__.py` 接入注册链
- [ ] 入参/出参 BaseModel（pydantic）继承正确，入参实现 `to_payload()`；出参按响应数据结构判定是否重写 `from_response()`（结构一致跳过，结构不同必须重写）；可选字段用 `Optional + None`，禁止空串/0 占位
- [ ] API 子类继承 `BaseSyncApi`/`BaseAsyncApi`，设置 `PATH`
- [ ] `execute` 方法签名已指向本接口的 Request/Response 子类（除非字段与基类完全一致）；异步接口已重写 `_build_result` 注入扩展字段
- [ ] `@<skill_name>_api_registry.register('leaf')`，leaf 在本子包内唯一，不含 `.`
- [ ] `api_category` / `api_label` 已设置（推荐）
- [ ] 测试位于 `tests/<skill_name>/`，**集成测试（不 mock 响应）**，每个枚举分支一个用例
- [ ] `python -m pytest` 全部通过
- [ ] 已在 `api/api_map.md` 追加一行（registry 名 / 路径 / 脚本）
- [ ] 可调参数已落到 `utils/settings.py`（全局进 `ProjectSettings`/`AuthEnvSettings`，局部在子包内建独立子类），业务代码零硬编码字面量
- [ ] 若修改了 `api/base/`，已向用户声明全局影响、列出受影响接口，并跑过 `common/tests/` 全量回归
