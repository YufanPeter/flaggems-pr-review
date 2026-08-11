# Code-Style 自动修复场景

## 为什么做这个场景

从上游 flagos-ai/FlagGems 近 120 个 PR 的 CI 失败数据看，`code-style` 是**压倒性的头号失败源**：

| 失败的 check | 出现次数（近 120 PR）|
|---|---|
| **code-style** | **16** |
| python-op | 5 |
| backend-tests (metax) | 4 |
| backend-tests (ascend) | 3 |
| 其他 backend-tests | 2 |

进一步看 code-style 内部失败的 hook（抽样 5 个真实失败 run）：

| Hook | 失败频次 | 性质 | 可否自动修 |
|---|---|---|---|
| **black** | 5/5 | 自动格式化 | ✅ 幂等、零语义风险 |
| **flake8** | 4/5 | lint 拦截 | ⚠️ 部分（未用 import 之类）可，逻辑类不可 |
| **isort** | 2/5 | import 排序 | ✅ 幂等 |
| **end-of-file-fixer** | 2/5 | 文件末尾换行 | ✅ |

**结论**：绝大多数 code-style 失败是「作者本地没跑 pre-commit 就提交」，属于纯机械、幂等、无语义风险的格式问题——是「验证→修复→提交」闭环最理想的第一个落地场景。

## 与 CI 的关系（为什么不是重复造轮子）

FlagGems 的 `linter.yml` 只是跑 `pre-commit/action`（对 PR 改动的文件跑）。CI 只告诉作者「你没跑 black」，不替他修。本工具补的正是「替他修」这一段：

```
CI 报 code-style 失败
      ↓
本工具 clone PR head 到临时目录（绑定 head SHA）
      ↓
对 PR 改动的文件跑 pre-commit → black/isort/eof 就地改文件
      ↓
fail-closed 门禁：重跑 pre-commit 必须全绿才认为可提交
      ↓
只 commit、不自动 push；打印将 push 的 diffstat 供人工确认
```

## 设计要点

1. **版本一致**：用 `python3.11 -m pre_commit run` 而非裸 `pre-commit`、更非直接调 black。显式绑定到 CI 用的 Python 3.11，让 hook 版本严格等于 flagos-ai/FlagGems `.pre-commit-config.yaml`（black 26.5.1、isort 5.12.0），不会因本地装了多个 pre-commit 或版本不同产生格式差异。
2. **只跑 PR 改动的文件**：用 `--files <PR 改动文件>` 而非 `--all-files`，对齐 CI 的 `pre-commit/action`。避免把 PR 没碰过、但本来就不合格式的历史文件一起改了，从而污染 PR、改变 CI 的判定范围。
3. **绑定 head SHA**：clone 后校验 `git rev-parse HEAD == PR head SHA`，防止修错版本。
4. **fail-closed**：可提交的充要条件是「修复后重跑 pre-commit 全绿」。这天然把 flake8 逻辑类错误（hook 改不了）挡在门外，标记为 `needs_human`，不生成 commit。
5. **默认不 push**：验证阶段只在临时 clone 里 commit，打印 diffstat 和 push 命令，人工确认后再 push。`auto_fixable` 时保留临时目录（内含待 push 的 commit），`clean` / `needs_human` 无产物则清理。

## 三种判定结果

| status | 含义 | 退出码 |
|---|---|---|
| `clean` | 首次跑 pre-commit 即全绿，无需修复 | 0 |
| `auto_fixable` | 修复后重跑全绿，已生成 commit（未 push）| 0 |
| `needs_human` | 仍有 hook 改不了的失败（通常 flake8 逻辑类）| 1 |

## 使用方式

### 命令行

```bash
cd /Users/yufan.shi/Desktop/PR-Review

# 默认：机械修复 + agent 修复 + 测试验证（全面，1-5 分钟）
python3.11 scripts/fix_code_style.py 5395

# 跳过测试验证（加速，1-3 分钟）
python3.11 scripts/fix_code_style.py 5395 --skip-tests
```

### Skill 调用

在 PR-Fix 仓库里，可以直接用 skill：

```bash
/fix-pr-style 5395                  # 默认全面修复
/fix-pr-style 5395 --skip-tests     # 跳过测试验证
```

## 三种判定结果

| status | 含义 | 输出 |
|---|---|---|
| `clean` | 首次跑 pre-commit 即全绿，无需修复 | "✅ 首次即全绿，无需修复" |
| `auto_fixable` | 修复成功，已生成 commit（未 push）| commit SHA + diffstat + push 命令 |
| `needs_human` | 仍有错误无法自动修复（逻辑类、复杂类型问题）| 失败的文件和错误详情 |

## Agent 修复能力

✅ **可靠自动修复**：
- F401 未使用的 import
- F841 未使用的变量
- E501 行太长
- E302/E303 空行问题
- 简单类型标注

⚠️ **中等风险**（需测试验证）：
- F821 未定义名字（可能是拼写错误或缺 import）
- E722 bare except

❌ **不能修复**（标记 needs_human）：
- 逻辑错误
- API 不兼容
- 复杂设计问题

首次运行会安装 pre-commit hook 环境（black/isort/flake8/clang-format），需要 1-3 分钟；后续运行直接使用缓存。
