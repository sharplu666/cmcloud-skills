# mclaw.api

同步/异步 AI 图片接口的**基础类模版库**。新增能力只需继承基类 + 定义入参/出参 dataclass，
即可获得统一的：API 请求重试、trace_id 日志、（异步）轮询直到终态。

## 目录结构

```
mclaw.api/
├── __init__.py            # 包导出
├── registry.py            # 单命名空间 API 注册表（ApiRegistry，每子包一个实例，无全局单例）
├── dispatcher.py          # 顶层联邦调度器（ApiDispatcher + _SubDispatcher，双入口调用）
├── base/
│   ├── __init__.py
│   ├── _http.py           # 内部共享：post_json_with_retry / post_xml_with_retry + extract_trace_id
│   ├── _base_api.py       # 内部共享基类 _BaseApi：HTTP 配置 / 脱敏 / 终态日志 / 结果构造钩子
│   ├── base_sync_api.py   # 同步接口基类（BaseSyncApi + SyncRequest + SyncResponse，继承 _BaseApi）
│   ├── base_xml_api.py    # XML 同步基类（BaseXmlSyncApi + XmlRequest + XmlResponse）
│   └── base_async_api.py  # 异步接口基类（BaseAsyncApi + AsyncSubmitRequest + AsyncSubmitResponse + AsyncPollResponse，继承 _BaseApi）
```

## 导入约定

所有 `common/` 子模块以**顶层 `common/` 目录**为 sys.path 根，使用绝对导入：

```python
from mclaw.api import BaseAsyncApi, AsyncSubmitRequest  # ✅ 推荐，从包顶层导入
from mclaw.api import ApiDispatcher, ApiRegistry  # ✅ dispatcher 与 registry 走顶层
from mclaw.api.search_fusion import search_fusion_api_registry  # ✅ 子包自治 registry
from mclaw.api.base import BaseSyncApi  # ✅ 也可显式走 base
from common.mclaw.api import

...  # ❌ 禁止带包前缀
from ..base import

...  # ❌ 禁止相对导入
```

调用方在 import 前将 `common/` 加入 sys.path 即可。`base/` 内部模块互相引用写
`from mclaw.api.base._http import ...`。

## 模块职责

| 模块 | 职责 |
|------|------|
| `registry.py` | 单命名空间 API 注册表 `ApiRegistry`：每子包实例化一个，存储本域叶子 API 子类，提供 register/get_class/build/is_sync/categories 等 |
| `dispatcher.py` | 顶层联邦调度器 `ApiDispatcher` + 子命名空间门面 `_SubDispatcher`：联邦各子包 registry，提供双入口调用（属性链 + dotted execute） |
| `base/_base_api.py` | Sync/Async 共享基类 `_BaseApi`：HTTP 配置、`__init__`、`_redact_payload`、`_build_result`、`_build_result_dict`（完整打印 `response.raw`）、`_format_result_msg` |
| `base/base_sync_api.py` | 同步接口基类：请求即返回结果（如 `ai_portrait_face_detect`），`SyncResponse.from_response` 默认展平 `data` |
| `base/base_async_api.py` | 异步接口基类：提交→轮询直到终态（绝大部分 AI 图片能力） |
| `base/_http.py` | 共享 HTTP 工具：重试、trace_id 提取与日志 |

具体类签名、字段、扩展规则见各模块 docstring。

## Registry 机制（联邦式 Service）

参考 `dev/skills/cm_cloud_organize/scripts/bucket/registry.py` 的设计：**类装饰器 + 类属性携带元信息 + 同步/异步 `issubclass` 自动判定**。与旧版的关键差异：**无全局单例**——每个子包 owns 自己的 `ApiRegistry` 实例，顶层 `ApiDispatcher` 联邦组合。

### 架构总览

```
mclaw.api/<skill_name>/__init__.py     ← 子包自治：xxx_api_registry = ApiRegistry(name='<skill>')
mclaw.api/dispatcher.py                ← 顶层联邦：ApiDispatcher 显式列举并 mount 各子 registry
```

| 名称 | 类型 | 用途 |
|------|------|------|
| `ApiRegistry(name)` | 单命名空间容器 | 每子包一个实例，存储本域叶子 API 子类 |
| `@<skill>_api_registry.register('leaf')` | 类装饰器 | 把 `BaseSyncApi`/`BaseAsyncApi` 子类按 leaf 名注册到本子包 registry |
| `ApiDispatcher(host, auth_fn, logger)` | 顶层联邦调度器 | 联邦各子 registry，提供双入口调用（属性链 + dotted execute） |

### 子包自治注册

每个子包在 `__init__.py` 创建自己的 registry，子 API 装饰器指向它：

```python
# mclaw.api/search_fusion/__init__.py
from mclaw.api.registry import ApiRegistry

search_fusion_api_registry = ApiRegistry(name='search_fusion')

from . import search_merge_file_api  # noqa: F401  副作用：注册
```

```python
# mclaw.api/search_fusion/search_merge_file_api.py
from mclaw.api.search_fusion import search_fusion_api_registry
from mclaw.api import BaseSyncApi, SyncRequest


@search_fusion_api_registry.register('search_merge_file')
class MergeFileSearchApi(BaseSyncApi):
    PATH = '/richlifeApp/aiService/api/text/intelligent/search/merge/file'
    api_category = 'search'  # 可选，默认 'misc'
    api_label = '个人云文件类整合搜索'  # 可选，默认 ''
```

注册规则：
- 仅接受 `BaseSyncApi` 或 `BaseAsyncApi` 的子类，否则抛 `TypeError`
- leaf 名不可含 `.`（保留给 dispatcher dotted 路径），否则抛 `ValueError`
- 重复注册同名 leaf 抛 `ValueError`（`f'API 名 {leaf!r} 已被 ... 占用'`）
- 注册的是**类本身**（不是实例），实例构造延迟到调用时

### 同步/异步自动判定

registry 在注册时不要求子类声明 `api_kind`，而是通过 `issubclass` 实时判定：

```python
search_fusion_api_registry.is_sync('search_merge_file')   # True
search_fusion_api_registry.is_async('search_merge_file')  # False
```

### 注册触发机制（重要边界）

`mclaw.api` 是基类库，**不内置任何 API 子类**。注册由子包 `__init__.py` 通过 import 触发；`mclaw.api/__init__.py` 末尾的 `from . import <skill_name>` 启动整条注册链。`ApiDispatcher.__init__` 再把这些子 registry 联邦进顶层调度器。

> Python 模块缓存保证同一模块多次 import 不会重复执行装饰器，因此不会触发重复注册的 `ValueError`。

## ApiDispatcher 统一调用

`ApiDispatcher` 是面向调用方的顶层联邦门面，持有 `host`/`auth_fn`/`logger` 公共参数，把每个子 registry 包成 `_SubDispatcher` 挂为实例真实属性（一级命名空间可 IDE 补全）。叶子调用通过 `_SubDispatcher.__getattr__` 域内派发。

### 构造

```python
from mclaw.api import ApiDispatcher

d = ApiDispatcher(
    host='https://api.example.com',
    auth_fn=get_auth_header,
    logger=my_logger,  # 可选
    cache_instances=True,  # 可选，默认 True（同一 dotted 名复用实例）
)
```

| 参数 | 用途 |
|------|------|
| `host` | API 域名，所有命名空间共享 |
| `auth_fn` | 返回鉴权 headers 的函数，每次请求前调用 |
| `logger` | 可选 logger，传入后所有子类共用 |
| `cache_instances` | 是否缓存子类实例，默认 `True`（推荐） |

### 双入口调用（完全等价）

```python
# 入口 1：属性链（一级命名空间是真实属性，IDE 可补全；叶子依赖 _SubDispatcher.__getattr__）
resp = d.search_fusion.search_merge_file(MergeFileSearchRequest(...))

# 入口 2：dotted 字符串（可 grep、可动态派发、便于跨域批处理）
resp = d.execute('search_fusion.search_merge_file', MergeFileSearchRequest(...))
```

两条入口在 `_SubDispatcher._execute` 收敛到同一条实例构造 + 调用路径，行为完全等价（单元测试覆盖等价性，见 `tests/test_dispatcher.py::TestDualEntryEquivalence`）。

### 返回类型

- 同步 API（`BaseSyncApi` 子类）→ `SyncResponse`
- 异步 API（`BaseAsyncApi` 子类）→ `AsyncPollResponse`（已自动轮询到终态）

调用方无需关心差异，registry 根据 `issubclass` 自动路由。

### 已注册 API 查询

```python
d.list_apis()                                  # ['search_fusion.search_merge_file', ...] dotted 全名
d.list_namespaces()                            # ['search_fusion', 'operation', 'search']
d.search_fusion.list_apis()                  # ['search_merge_file', 'search_merge_image', 'search_face_recognize']  域内叶子名
'search_merge_file' in d.search_fusion._registry  # True（域内查询）
```

### 限制（重要）

- `host`/`auth_fn` 对所有命名空间共享。若不同 API 需要不同 host/auth，**请直接构造具体子类实例**，不走 `ApiDispatcher`。
- 一级命名空间（如 `d.search_fusion`）是实例真实属性，IDE 可补全；二级叶子（如 `d.search_fusion.search_merge_file`）依赖 `_SubDispatcher.__getattr__`，IDE 无法静态补全。需要类型提示时优先用 `d.execute('ns.leaf', req)`。
- `registry.build` 只传 `host`/`auth_fn`/`logger`。若某些子类构造函数需要额外参数，需绕过 registry 直接实例化。

## 分类视图（域内）

子类通过两个可选类属性携带元信息，供**本子包 registry** 的 `categories()` 派生域内分类视图：

| 类属性 | 默认值 | 用途 |
|--------|--------|------|
| `api_category` | `'misc'` | 分类名，如 `'detect'` / `'image'` / `'avatar'` |
| `api_label` | `''` | 中文标签，如 `'人脸检测'` / `'文生图'` |

```python
search_fusion_api_registry.categories()
# {
#     'search': {'name': 'search', 'label': '...', 'kind': 'sync',
#                'members': ['search_merge_file', 'search_merge_image']},
#     ...
# }
```

`kind` 字段表示该分类下首次出现的 API 类型（`'sync'` / `'async'`）。细粒度判定请用 `is_sync(name)` / `is_async(name)`。

## 日志约定

**禁止**在基类与子类中直接调用 `logger.info/warning`。所有日志统一通过
`utils.logger.status_log` 打印，由 `status_log` 根据 `msg` 内容自动决定级别
（`msg` 含 `fail`/`error` → WARNING，含 `内部异常错误` → ERROR，其余 → INFO）。

### status_log 函数签名

```python
def status_log(msg, logger=..., info_dict=None, server_type='API'):
    ...
```

| 参数 | 用途 |
|------|------|
| `msg` | **日志消息**（不是状态）。如 `request_success` / `poll_start`，描述本次日志"说了什么"。`status_log` 会按 `msg` 中是否含 `fail`/`error`/`内部异常错误` 自动决定日志级别。 |
| `logger` | logger 实例，由基类构造时注入。 |
| `info_dict` | 系统级 / 类级标识字典（详见下表）。 |
| `server_type` | 事件来源类别，本项目固定取 `HTTP` / `SYNC` / `ASYNC`。 |

> **命名说明**：参数叫 `msg` 而非 `status`，是为了和"业务状态"（如异步任务的 status 1-5）区分。
> `msg` 是日志消息内容，业务状态值不应作为 `msg` 传入。

### info_dict 取值规则（重要）

`info_dict` **只放系统级 / 类级标识**，用于回答"谁在记、哪一次操作"：

| 类别 | 允许的字段 | 说明 |
|------|-----------|------|
| 类级 | `api` | 子类名（如 `FaceDetectApi`），由 `type(self).__name__` 得到 |
| 系统级 | `trace_id` | 分布式追踪 ID，跨服务串联一次请求 |
| 系统级 | `taskId` | 异步任务 ID，串联一次异步操作的提交+轮询 |
| 全局 | `requestId` | 进程级请求标识（16 位 uuid），由 `GlobalLogInfoSettings.REQUEST_ID` 提供，``status_log`` 自动注入 |

**禁止放入 info_dict** 的内容：
- ❌ 函数入参 / 瞬态状态：`url`、`attempt`、`retry_delay`、`payload`
- ❌ 异常细节：`error`、`exc`（应通过 `RuntimeError` 链路向上传递）
- ❌ API 业务返回：`code`、`message`、`status` 值、`queueOffset`、`fileUrlList`、`fileInfoList`

> **全局字段自动注入**：`status_log` 会把 `GlobalLogInfoSettings`（`mclaw/utils/settings.py`）
> 中的字段合并到每条日志的 `info_dict`，无需调用方手动传。当前含 `requestId`。
> 调用方显式传入的同名 key 优先（覆盖全局值）。

调用形式：

```python
from mclaw.utils.logger import status_log

status_log(
    msg='submit_success',  # 日志消息（关键字传参，语义清晰）
    logger=self.logger,
    info_dict={  # 只放系统级 / 类级标识
        'api': type(self).__name__,
        'taskId': task_id,
        'trace_id': trace_id,
    },
    server_type='ASYNC',  # HTTP / SYNC / ASYNC，标识事件来源
)
```

### 基类已内置的事件

| server_type | msg | info_dict | 默认级别 |
|-------------|-----|-----------|---------|
| HTTP | `request_success` | `{trace_id}` | INFO |
| HTTP | `request_fail` | `{}` | WARNING |
| HTTP | `auth_fail` | `{}` | WARNING |
| SYNC | `execute_success` | `{api, trace_id}` | INFO |
| SYNC | `execute_fail` | `{api, trace_id}` | WARNING |
| ASYNC | `submit_success` | `{api, taskId, trace_id}` | INFO |
| ASYNC | `poll_start` | `{api, taskId, trace_id}` | INFO |
| ASYNC | `poll_attempt` | `{api, taskId}` | INFO |
| ASYNC | `poll_success` | `{api, taskId, trace_id}` | INFO |
| ASYNC | `poll_fail` | `{api, taskId, trace_id}` | WARNING |

### 异常捕获与错误记录（强制）

**所有 `try/except` 块**在捕获后，**必须先用以下固定格式记录错误**，再做后续处理
（重试 / `raise` / 降级）。目的：完整堆栈单行化写入日志，便于聚合检索与定位。

#### 固定格式

```python
import traceback

err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
```

- `Error={str(e)}`：异常简述，前缀固定为 `Error=`
- `str(traceback.format_exc()).replace('\n', '')`：完整堆栈**移除所有换行**，
  保证日志单行可读、可被日志系统聚合
- 拼接后整体传入 `status_log` 的 `msg` 字段，**不再单独 `print` / `log.exception`**

#### 必须带模块标志（双重标识）

错误记录必须能回答"是哪个模块的哪个函数抛的"。**模块标志精确到函数级**，
不只是模块名 —— 一行日志能在不看堆栈的情况下直接定位到出错的源代码位置。

1. **`msg` 前缀加 `[<模块名>.<函数名>]` 或 `[<类名>.<方法名>]`**：

   | 场景 | 标志格式 | 示例 |
   |------|---------|------|
   | 工具函数 | `<子模块名>.<函数名>` | `[_http.post_json_with_retry]` |
   | 类方法（具体子类） | `<类名>.<方法名>` | `[FaceDetectApi.execute]` |
   | 基类方法（多子类继承） | `{type(self).__name__}.<方法名>` | `[{type(self).__name__}._poll]`（运行时展开为 `[TextToImageApi._poll]` 等） |
   | classmethod / 静态方法 | `<类名>.<方法名>` | `[AsyncPollResponse.from_response]` |

   子模块名取**最末一段**（不带 `mclaw.api.base.` 前缀），如 `_http` / `decrypt` / `auth`。
   前缀一律用方括号包裹，紧跟事件名 + 空格 + `err_detail`。

2. **`info_dict['api']`**：按原约定填 `type(self).__name__`；
   工具函数（无 `self`）填子模块名（如 `_http`）

> **为什么函数级而非仅模块级**：同一个模块可能有多个 try/except（如 `_http.py`
> 同时有 auth 失败和 request 失败两个分支），仅 `[<模块名>]` 在日志聚合时仍需翻
> 堆栈才能定位；带上函数名后，`[_http.post_json_with_retry]auth_error` 一眼可知
> 是 `post_json_with_retry` 内的 `auth_fn()` 失败。这条经验来自 `_http.py` 实践。

> `msg` 含 `error` / `fail` 关键字 → WARNING；含 `内部异常错误` → ERROR；其余 INFO（级别判定规则见本章节日志约定开头）。
> `err_detail` 一律走 `msg`，**不放 `info_dict`**（`info_dict` 仍只放系统级标识）。

#### 示例

子类方法（有 `self.logger`，类名 + 方法名）：

```python
import traceback
from mclaw.utils.logger import status_log


class FaceDetectApi(BaseSyncApi):
    def execute(self, req):
        try:
            return self._call(req)
        except Exception as e:
            err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
            status_log(
                msg=f"[FaceDetectApi.execute]detect_error {err_detail}",
                logger=self.logger,
                info_dict={'api': type(self).__name__, 'trace_id': req.trace_id},
                server_type='SYNC',
            )
            raise  # 记录后必须向上抛，禁止吞异常
```

基类方法（运行时拿子类名）：

```python
class BaseAsyncApi(ABC):
    def _poll(self, task_id, ...):
        try:
            status_int = int(status_value)
        except (TypeError, ValueError) as e:
            err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
            status_log(
                msg=f"[{type(self).__name__}._poll]status_error {err_detail}",
                logger=self.logger,
                info_dict={'api': type(self).__name__, 'taskId': task_id, 'trace_id': trace_id},
                server_type='ASYNC',
            )
            raise RuntimeError(...) from e
```

工具函数（无 `self.logger`，注入 `log`，模块名 + 函数名）：

```python
import traceback
from mclaw.utils.logger import status_log


def post_json_with_retry(url, payload, *, auth_fn, log, ...):
    try:
        headers = auth_fn()
    except Exception as e:
        err_detail = f"Error={str(e)}" + str(traceback.format_exc()).replace('\n', '')
        status_log(
            msg=f"[_http.post_json_with_retry]auth_error {err_detail}",
            logger=log,
            info_dict={},
            server_type='HTTP',
        )
        raise
```

#### 禁止

- ❌ `except: pass` / `except Exception: pass` 静默吞异常
- ❌ 只记 `str(e)`，丢掉 `traceback.format_exc()` 完整堆栈
- ❌ 把 traceback 原文（含 `\n`）直接写入日志
- ❌ 把 `err_detail` 塞进 `info_dict`（违背"info_dict 只放系统级标识"原则）
- ❌ 记录后不 `raise`，导致异常被静默吞掉（除非该层显式负责容错降级）

### 子类扩展规则

- 子类自定义 `msg` 时，**避免**直接复用上述保留名；推荐 `<verb>_<result>` 风格
  （如 `detect_success` / `detect_fail`）。
- 业务字段（业务入参、API 返回值）一律不放 `info_dict`；如需排查，放进
  `RuntimeError` 消息或独立写文件。
- `server_type` 必须取 `SYNC` / `ASYNC` / `HTTP` 之一，便于日志聚合时按来源过滤。
- 调用时统一用 `msg=` 关键字传参，避免和未来新增的参数混淆。
