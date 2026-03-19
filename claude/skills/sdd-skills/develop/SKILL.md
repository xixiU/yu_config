---
name: develop
description: 通过 Agent Teams 编排并行开发。Leader 读取 spec 产出物，创建开发团队，按批次派发 teammate 在 worktree 中独立编码+自验，协调依赖传播，实时追踪进度。
---

> **知识库路径**：`~/knowledge-base/`。如果该目录不存在，提示用户：`知识库目录 ~/knowledge-base/ 不存在，请先拉取知识库。`

# Agent Teams 并行开发

## 概述

使用 Agent Teams 编排 SDD/TDD 驱动的并行开发。Leader 读取已批准的 spec，创建开发团队，将任务分配给 teammates。每个 teammate 在 worktree 中独立编码，完成后执行自验。

**核心原则：** Leader 协调调度，teammates 独立执行，每个 teammate 的 spawn prompt 必须包含完成任务所需的全部信息（teammates 不继承 leader 的对话历史）。

## 铁律

```
1. spec.md 状态必须是 approved 才能开始开发
2. Teammate 必须在 worktree 中工作，绝不直接改源仓库
3. 每个 teammate 完成后必须自验（编译检查 + 测试用例逐条验证）
4. API 模块变更必须先传播依赖再构建下游
5. Leader 负责编排和决策，不直接写业务代码
6. 避免多个 teammates 编辑同一文件 — 按文件归属拆分任务
```

## 前置条件

<HARD-GATE>
1. 当前 workspace 存在 spec.md 且状态为 approved
2. repos.md 中列出的所有 worktree 目录存在且为有效 git 仓库

如果 spec.md 不存在或未被批准，立即停止，先执行 `/spec`。
如果任何 worktree 目录不存在，立即停止，提示用户重新执行 `/spec` Phase 2 创建 worktree。
</HARD-GATE>

---

## 步骤 1：加载 Spec 与知识（Leader）

1. 读取 `.ai-workspace/tasks.md`：
   - 第 2 章「任务清单」→ 任务列表（ID、描述、依赖、工作目录）
   - 第 3 章「构建部署顺序」→ 构建顺序
   - 第 5 章「Worktree 映射」→ 任务与 worktree 的对应关系
2. 读取 `.ai-workspace/contracts.md` → 每个任务关联的接口定义
3. 读取 `.ai-workspace/testcases.md` → 每个任务关联的测试用例（通过 test_ref）
4. **验证 worktree** — 逐个检查 repos.md 中的 worktree 路径是否存在且为有效 git worktree
5. 加载知识：
   - `~/knowledge-base/`（overview, call-chains, conventions, pitfalls）
   - 各 worktree 中的 CLAUDE.md → 组件级知识
   - `~/knowledge-base/insights/_index.md`（如存在）→ 按关键词匹配经验

## 步骤 2：制定执行计划（Leader）

1. 按 `depends_on` 构建任务依赖图
2. 按 worktree 分组任务（同一 worktree 的任务分给同一 teammate）
3. 确定执行批次（无依赖 → 第一批并行，依赖前批 → 后续批次）
4. 标记 API 模块任务，确保在下游任务之前完成
5. 展示执行计划给用户确认，等待确认后继续

## 步骤 3：创建团队并派发 Teammate（Leader）

创建开发团队，为每个批次的任务 spawn teammates。

**每个 teammate 的 spawn prompt 必须包含完成任务所需的全部信息：**

- **任务描述**（从 tasks.md 提取，含验收标准）
- **接口契约**（从 contracts.md 提取相关 API 定义：方法签名、入参出参、行为规约、错误码）
- **测试用例**（从 testcases.md 提取关联的 TC：输入、期望结果、验证方式）
- **编码规范**（从 ~/knowledge-base/conventions.md 提取相关章节）
- **已知坑点**（从 ~/knowledge-base/pitfalls.md 筛选与本任务相关的条目）
- **组件知识**（从对应 worktree 的 CLAUDE.md 提取：模块职责、关键类、数据表）
- **工作目录**（worktree 绝对路径、分支名、基准分支）
- **要修改的文件路径**（明确列出）
- **完成标准**：
  1. 严格按接口契约实现
  2. 所有测试用例逐条自验通过
  3. 编译检查通过
  4. git add 所有变更文件

> **关键：** Teammates 不继承 leader 的对话历史。不要说"参考前面的讨论"或"去读 contracts.md"，直接把内容粘贴到 spawn prompt 中。

**团队规模建议：** 3-5 个 teammates，每人 5-6 个任务。同一仓库多个 teammate 并行时，leader 需按文件归属分配，避免编辑冲突。

## 步骤 4：监控与协调（Leader）

1. 关注 teammate 消息（完成报告、提问、阻塞）
2. teammate 完成任务后标记完成
3. 当一个批次全部完成后，启动下一批次的 teammates
4. 如果 teammate 被阻塞，帮助解决或上报给用户
5. **实时更新 progress.md**（见步骤 7）

**处理 teammate 提问：**
- 需求问题 → 查 spec.md / tasks.md，找到答案则转发，否则问用户
- 代码问题 → 查 ~/knowledge-base/ 和 worktree CLAUDE.md，找到则转发，否则让 teammate 自行探索
- 任务描述缺陷 → 立即停下，与用户讨论

**冲突检测：** 启动下一组前检查是否有冲突的变更。有冲突必须先解决，不得进入评审。

## 步骤 5：Teammate 自验（每个 Teammate）

每个 teammate 完成编码后**必须执行**：

**a) 编译检查**
```bash
cd {worktree-path}
mvn compile -pl {module} -am -q 2>&1 | tail -20
```
编译失败 → 自行修复 → 重新编译，直到通过。

**b) 测试用例逐条验证**
对照 spawn prompt 中的测试用例表，逐条检查代码是否覆盖。

**c) 输出自验报告**
```markdown
# Self-validation Report: {task-id}

## 编译状态: PASS / FAIL

## 测试用例验证
| ID | 结果 | 说明 |

## 修改文件清单
| 文件 | 操作 | 变更摘要 |

## 发现的问题或经验
```

**d) 暂存变更**
`git add` 所有变更，确认 `git status` 干净。

## 步骤 6：API 依赖传播（Leader）

当一个批次包含 API 模块任务且该批次完成后：

1. 在 API worktree 中执行 `mvn install -pl {api-module} -DskipTests`
2. 找到下游消费方 pom.xml 中的 API 依赖，更新版本号
3. 在下游 worktree 中验证编译通过
4. 编译通过 → 启动下一批次；编译失败 → 诊断修复

<HARD-GATE>
修改了被依赖的包却未重建和传播，下游模块必然编译失败。不得跳过。
</HARD-GATE>

对前端项目：检查 `package.json` 依赖是否需要更新。

## 步骤 7：生成进度报告（Leader）

**实时更新** `.ai-workspace/develop/progress.md`：

```markdown
# 开发进度

更新时间: {timestamp}

## 总览
- 总任务: {N}
- 已完成: {M} / {N}
- 当前批次: {batch}
- API 传播: {done/pending/N-A}

## 任务状态
| ID | 标题 | 状态 | Teammate | 编译 | 自验 | 完成时间 |
|----|------|------|----------|------|------|---------|

## 变更文件汇总
| 文件 | 操作 | Worktree | 任务 |

## 发现的问题与经验
{从各 teammate 自验报告中汇总}
```

每个 teammate 完成时立即更新，不等全部完成。

## 步骤 8：完成与清理（Leader）

1. 所有任务完成，所有自验 PASS
2. API 依赖传播完成（如适用）
3. 无合并冲突
4. 沉淀坑点经验 → `~/knowledge-base/insights/platform/`
5. 清理团队
6. 输出：

```
develop 阶段完成：
- 任务: {M}/{N} 完成
- 自验: {P}/{Q} 测试用例通过
- 编译: 全部 PASS
- API 传播: 完成

下一步: /review
```

---

## 产出物

| 文件 | 路径 | 用途 |
|------|------|------|
| progress.md | `.ai-workspace/develop/progress.md` | 实时开发进度 |
| self-validation-report.md | 各 worktree 根目录 | teammate 自验报告 |
| 代码变更 | 各 worktree 中 | 实际代码改动 |

## 危险信号

**绝不要：**
- spec 未 approved 就开始开发
- 在源仓库中直接改代码（必须用 worktree）
- 跳过 worktree 校验直接派发任务
- 跳过自验（编译检查 + 测试用例验证）
- 忽略 API 依赖传播
- spawn teammate 时不给足上下文（说"去读 xxx 文件"而不是直接粘贴内容）
- 让多个 teammates 同时编辑同一文件
- 忽略 teammate 的提问（必须回答或上报）
- Leader 自己动手写业务代码而不是委派 teammate

**始终要：**
- spawn prompt 包含 teammate 完成任务所需的全部信息
- 完成即更新 progress.md
- 编译失败必须修复后才算完成
- 定期检查 teammate 进度，主动协调
- 完成后清理团队
- 记录踩坑经验供后续沉淀

## 常见自我合理化

| 借口 | 现实 |
|------|------|
| "teammate 自己能搞懂代码库" | spawn prompt 给足上下文花 10 秒，teammate 自己探索花几小时 |
| "任务是独立的，不需要协调" | 即使独立的任务在集成时也可能冲突 |
| "跳过自查，review skill 会发现问题" | 自查能低成本捕获 80% 的问题 |
| "只改了一点，不用重建" | 接口变更会导致所有下游模块编译失败 |
| "直接告诉 teammate 去读文件就行" | teammates 不继承 leader 对话历史，可能找不到或跳过 |

## 集成

**从工作区读取：**
- `.ai-workspace/spec.md` — 需求规约（状态检查）
- `.ai-workspace/contracts.md` — 接口契约
- `.ai-workspace/testcases.md` — 测试用例
- `.ai-workspace/tasks.md` — 已批准的任务清单
- `.ai-workspace/repos.md` — worktree 清单
- `~/knowledge-base/` — 系统架构、调用链路、规范、坑点
- 各 worktree CLAUDE.md — 组件级知识

**写入工作区：**
- `.ai-workspace/develop/progress.md` — 实时开发进度

**下一个 skill：** 开发完成后，执行 `/review` 进行代码评审。
