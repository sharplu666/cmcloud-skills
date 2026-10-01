# 常见示例

## 精选 / 去重

### 示例 1: 整集精选 N 张

```
# 用户输入：从这批结果里精选3张给我看
# 执行：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --pick 3
# 预期：整集精选 3 张，产出 select.jsonl；回执转述即可（不整理）
```

### 示例 2: 每月精选（分桶）

```
# 用户输入：每月精选3张，待会再决定怎么放
# 执行：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --bucket month --pick 3
# 预期：每月各精选 3 张，select.jsonl 每行带 month bucket；存活数 = 月数×3
```

### 示例 3: 整集去重

```
# 用户输入：先把重复的去掉
# 执行：
python3 {baseDir}/scripts/main.py refine --kind dedup --from op_<6位编码>/search.jsonl
# 预期：整集去重（精确 contentHash + 相似图 API），产出 dedup.jsonl
```

## 整理方向推荐（recommend）

### 示例 4: 没说整理去向，先拿三情形推荐

```
# 用户输入：帮我整理这批照片
# 执行（显式 --target recommend）：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target recommend --bucket month
# 预期：回执并列情形 1 回忆故事 / 情形 2 相册 / 情形 3 子目录 + 三条带 --target 的重跑
#       命令；桶行带 <bucketId>（--only 选桶引用，编号与 target plan 一致）。仅预览
#       不落盘（不产 plan.jsonl，不能 submit）。用户选「相册」后原样重跑
#       （只加 --target album），进入相册单值流程
```

## 整理到个人云目录（drive）

### 示例 5: 按年份归档到指定文件夹

```
# 用户输入：刘德华的图片按年份归档到测试文件夹
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --bucket year --parent-path 测试文件夹
# 预期：按年分桶进「测试文件夹/2024/…」，回执 renderText 预览待用户确认
```

### 示例 6: 多维平铺成一层拼名目录

```
# 用户输入：按年份和类型平铺成一层「年_类型」目录
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --mode cross --bucket year,fileExtension
# 预期：一层平铺目录，桶名拼接（如「2024_jpg」）
```

### 示例 7: 多维嵌套层级目录

```
# 用户输入：先按年再按月份层文件夹放
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --bucket year,month
# 预期：多维缺省嵌套，产「2024/2024-08/…」层级目录；要一层拼名才需 --mode cross
```

### 示例 8: 桶内规则化重命名

```
# 用户输入：按月份整理，文件重命名成「月份_序号」
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --bucket month --rename-template {month}_{index}.{ext}
# 预期：{month} 渲染为该桶月值（如 2024-08），得「2024-08_001.jpg」；预览 renderText 可见新名
```

### 示例 9: 未知桶排除

```
# 用户输入：按城市分，识别不出城市的就不要了
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --bucket city --unknown drop
# 预期：未知城市的照片被排除
```

### 示例 10: 每月精选整理到指定文件夹（refine + plan 两步）

```
# 用户输入：帮我搜索名为刘德华的图片，每月精选3张整理到zjx文件夹
# 执行（精选已移到 refine，两步）：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --bucket month --pick 3
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/select.jsonl --target drive --parent-path zjx
# 预期：refine 每月各精选 3 张写子集；plan 读子集 month bucket 进「zjx/2026-08/…」（保留按月结构）
```

### 示例 11: 每月精选合并塌平进同一文件夹（两步）

```
# 用户输入：每月精选3张，全部放进同一个文件夹
# 执行（两步：refine 分桶精选 + plan 合并塌平）：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --bucket month --pick 3
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/select.jsonl --target drive --merge-into 精选
# 预期：先每桶精选（refine）再合并（plan merge-into），共 月数×3 张平铺进「精选/」（不是 3 张）
```

### 示例 12: 只保留预览 bucketId 命中的桶

```
# 用户输入：类型分桶后只保留预览里 bucketId 1、3 的桶
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target drive --bucket fileExtension --only 1,3 --parent-path zjx
# 预期：只保留 bucketId 命中的桶（bucketId 取自上次 plan 回执 renderText 的 <bucketId>；编号聚类时冻结、跨 target 稳定，换维度需重看）
```

## 整理到相册 / 回忆故事

### 示例 13: 按月份成相册

```
# 用户输入：把这些照片按月份整理成相册
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target album --bucket month
# 预期：每月一个相册（桶名=相册名），回执 renderText 预览待用户确认
```

### 示例 14: 每月精选合成单个相册

```
# 用户输入：按月份每月精选3张，合成一个相册
# 执行：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --bucket month --pick 3
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/select.jsonl --target album --merge-into 月度精选
# 预期：refine 每月各精选 3 张写子集（month 标签）；plan 读子集标签后合并成一个「月度精选」相册（共 月数×3 张）
```

### 示例 15: 生成回忆故事

```
# 用户输入：用这批照片生成一个回忆故事
# 执行：
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/search.jsonl --target memory --merge-into 我们的2026
# 预期：全部照片合成一个池、精选一次，产出单个回忆故事（全局按质量选前 50，≤50 张）
```

## 提交与进度

### 示例 16: 确认方案后提交

```
# 用户输入：（看过 plan 预览后）同意，就这样整理
# 执行：
python3 {baseDir}/scripts/main.py organize --step submit --from op_<6位编码>/plan.jsonl --processing-hint "刘德华图片整理"
# 预期：小任务回执直接出结果；异步任务回执返回 taskId 供 status/retry 查询，
#       data.target（如 album）留给 retry --target 用
```

### 示例 17: 查任务进度

```
# 用户输入：刚才那个整理任务怎么样了？
# 执行：
python3 {baseDir}/scripts/main.py organize --step status --task-id <taskId>
# 预期：返回该任务当前进度；完成通知（System-Event）到了也会带 taskId，同命令查询
```

### 示例 18: 失败任务重试

```
# 用户输入：那个任务失败了，再试一次
# 执行：
python3 {baseDir}/scripts/main.py organize --step retry --task-id <taskId> --target album
# 预期：对该任务发起重试（--target 取当时 submit 回执 data.target），回执返回最新进度
```

## 高级用法

### 示例 19: 去重后再整理（dedup 子集承接）

```
# 用户输入：这批照片先去重，再按年份归档到测试文件夹
# 执行（两步：refine 去重 + plan 重新聚类）：
python3 {baseDir}/scripts/main.py refine --kind dedup --from op_<6位编码>/search.jsonl
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/dedup.jsonl --target drive --bucket year --parent-path 测试文件夹
# 预期：去重子集无桶标签（flat），plan 不复用子集分桶、用 --bucket 重新按年聚类
```

### 示例 20: 精选 + 重命名 + 未知桶扔掉（多参数组合）

```
# 用户输入：每月精选3张放进「月度」文件夹，文件名统一成「月_序号」，没识别出月份的就不要
# 执行（两步组合）：
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码>/search.jsonl --bucket month --pick 3
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码>/select.jsonl --target drive --parent-path 月度 --rename-template {bucket}_{index}.{ext} --unknown drop
# 预期：子集 month bucket 成叶、桶内按模板重命名（如「2026-08_1.jpg」）、未识别月份的被排除
```

## 合并（merge）

### 示例 21: 合并两批搜索，再按月精选

```
# 用户输入：7月拍的和8月拍的分开搜的，合到一起，每月精选3张
# 执行：
python3 {baseDir}/scripts/main.py refine --kind merge --from op_<6位编码1>/search.jsonl,op_<6位编码2>/search.jsonl
python3 {baseDir}/scripts/main.py refine --kind select --from op_<6位编码3>/merged.jsonl --bucket month --pick 3
# 预期：merge 产新语料 op_<6位编码3>/merged.jsonl（跨批同 fileId 保首现）；
#       对它按月精选，select.jsonl 落回同一会话 op_<6位编码3>/
```

### 示例 22: 合并多个精选子集，汇总成一个相册

```
# 用户输入：把这几个会话各自精选过的结果并成一个相册
# 执行：
python3 {baseDir}/scripts/main.py refine --kind merge --from op_<6位编码1>/select.jsonl,op_<6位编码2>/select.jsonl,op_<6位编码3>/dedup.jsonl
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码4>/merged.jsonl --target album --merge-into 精选汇总
# 预期：子集并入新语料（原桶标签降级 srcBucket 存档，不参与分桶）；
#       merged 无活动标签，album 用 --merge-into 命名单册
```

### 示例 23: 合并后直接按月整理到目录

```
# 用户输入：两批搜索结果合起来，按月份归档
# 执行：
python3 {baseDir}/scripts/main.py refine --kind merge --from op_<6位编码1>/search.jsonl,op_<6位编码2>/search.jsonl
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码3>/merged.jsonl --target drive --bucket month --parent-path 归档
# 预期：merged 是语料，plan 与读 search.jsonl 同路径按月聚类，产「归档/2026-07/…」
```
