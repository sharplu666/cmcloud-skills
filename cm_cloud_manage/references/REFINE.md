# 精选 / 去重 / 合并（refine）

```
python3 {baseDir}/scripts/main.py refine --kind <dedup|select> --from <handle>/{search|merged}.jsonl
               [--mode …] [--bucket …] [--pick N]
python3 {baseDir}/scripts/main.py refine --kind merge --from <h1>/<f1>.jsonl,<h2>/<f2>.jsonl[,…]
```

## 参数速查

| 参数 | 适用 | 取值 | 说明 |
|---|---|---|---|
| `--kind` | 全部 | `dedup` / `select` / `merge` | 必填。dedup=去重；select=精选（须配 `--pick`，自动开去重）；merge=合并多 jsonl 产新语料 |
| `--from` | dedup/select | `op_<6位编码>/search.jsonl` 或 `op_<6位编码>/merged.jsonl` | 单输入，只认语料类文件；不接受对子集再 refine，也不接受 CSV 多输入 |
| `--from` | merge | CSV ≥2 项 | 每项 `op_<6位编码>/{search\|dedup\|select\|merged}.jsonl`，任意组合可互混、merged 可循环再合并；plan 等整理产物拒绝 |
| `--mode` | dedup/select | `cross` / `hierarchical` | 分桶模式；单维度无需传；hierarchical 在子集中降维成单层拼名 |
| `--bucket` | dedup/select | 单值或 CSV | 分桶维度；传则 per-bucket refine（子集每行带 bucket 标签），不传则整集 refine（无桶标签） |
| `--pick` | select | 正整数 | 每桶精选前 N 张；select 必填；dedup / merge 不传 |

**分桶维度对照**与 organize plan 完全一致（`year`/`month`/`fileExtension`/`city`/`peopleNameList` 等，维度全集见 [ORGANIZE.md](./ORGANIZE.md)）。

## 两种作用范围（dedup/select）

- **整集 refine（不传 `--bucket`）**：对整个结果集去重 / 精选前 N，子集每行 `bucket` 为空串。等价于「不分桶直接精选 N 张」「整集去重」。
- **per-bucket refine（传 `--bucket`）**：先分桶，每桶各自去重 / 精选前 N，子集每行带该文件所属桶的标签。`--bucket month --pick 3` = 每月各挑 3 张，存活数 = 月数 × 3。
- **精选质量门（仅 select）**：精选与「整理到回忆故事」同一套规则——先剔除证件/截图等标签图片与无拍摄时间的图片（缺拍摄时间的结果可能被全剔），再去重、按质量分取前 N；`--kind dedup` 不做剔除。

## merge：合并产新语料

```
# 用户输入：上周搜的「聚餐」和今天搜的「团建」合并到一起，按月整理
python3 {baseDir}/scripts/main.py refine --kind merge --from op_<6位编码1>/search.jsonl,op_<6位编码2>/search.jsonl
python3 {baseDir}/scripts/main.py organize --step plan --from op_<6位编码3>/merged.jsonl --bucket month --target drive
# 预期：产新会话语料 op_<6位编码3>/merged.jsonl（跨输入同 fileId 只留首现，重叠不重复计数）；
#       merged 无桶标签，plan 按 --bucket 自行聚类；要内容级去重（相似图）对 merged 再跑 --kind dedup
```

## 接到整理

精选 / 去重 / 合并后要整理时，用 `organize --step plan --from <handle>/<file>.jsonl` 承接
（search/merged 语料按 plan 参数聚类；带标签子集复用子集分桶、flat 子集重聚类，见 [ORGANIZE.md](./ORGANIZE.md)）。

## 不受理

对子集再 refine（`refine --kind dedup --from op_<6位编码>/select.jsonl`）不支持——子集已是精选/去重产物，
先 `--kind merge` 并成新语料再 refine；换维度重 refine 请用语料文件（search / merged）重来。

更多组合用例（合并多批搜索、合并后按月精选）见 [examples.md](./examples.md)。
