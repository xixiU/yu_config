---
name: review
description: 三阶段代码审查：自动化验证 → Spec 符合性检查 → 代码质量深度检查。融合 spec 驱动审查、143 检查点清单和自动化验证循环。
---

# 三阶段代码审查 (Review)

## 概述

融合 Spec 驱动审查、代码质量检查点清单和自动化验证循环的全面代码审查技能。三个阶段层层递进，确保代码从编译正确性到需求符合性到深层质量全覆盖。

**核心理念：**
1. 自动化先行 — 能用工具检测的问题不靠人眼
2. Spec 对照 — 不是凭感觉 review，而是对着 spec 逐条核对
3. 深度质量 — 结合检查点清单和项目踩坑记录做深层审查
4. 问题可操作 — 每个发现必须有修复建议，支持自动修复和重检

## 铁律

```
1. develop 阶段必须完成才能 review
2. Critical/Major 问题必须修复后重新 review
3. 每个发现必须标注级别（Critical/Major/Minor）
4. 审查必须对照 contracts.md 的接口契约和 testcases.md 的测试用例
5. 自动修复最多 3 轮，超过则人工介入
```

## 前置条件

<HARD-GATE>
1. 当前 workspace 的 develop 阶段已完成（progress.md 存在且所有任务完成）
2. spec.md 存在且状态为 approved
3. 代码已在 worktree 或 feature 分支中，可正常编译
</HARD-GATE>

## 问题分级

| 级别 | 标记 | 定义 | 处理方式 |
|------|------|------|----------|
| Critical | P0 | 安全漏洞、数据丢失、破坏现有功能 | 必须修复，修复后重跑失败阶段 |
| Major | P1 | 规范违反、错误模式、缺少边界处理、权限缺陷 | 必须修复，修复后重跑失败阶段 |
| Minor | P2 | 风格建议、命名优化、可选改进 | 记录即可，可忽略 |

---

## 变更识别（Phase 前置）

读取 `.ai-workspace/repos.md` 获取 worktree 清单，对每个 worktree 收集变更：

```bash
# 对每个 worktree 分别执行
cd {worktree路径}

# 获取所有变更的 diff
git diff {base-branch}...HEAD

# 列出所有变更的文件
git diff --name-only {base-branch}...HEAD

# 查看提交历史
git log --oneline {base-branch}..HEAD
```

> **注意：** 每个仓库的 base-branch 可能不同，需从 repos.md 或各仓库的实际情况确定。汇总所有仓库的变更后，再进入 Phase 0。

**后续三个 Phase 的审查范围限定为此处识别到的变更文件。**

---

## Phase 0: 自动化验证

**目标：用工具扫描能自动发现的问题，节省人工审查精力。**

### 0.1 编译检查

针对项目类型执行编译验证：

```bash
# Java 项目（Maven）
mvn compile -pl {changed-modules} -am -q 2>&1 | tail -50

# 如果是多模块项目，按构建依赖图顺序编译
# 参考 CLAUDE.md 中的"组件构建依赖图"
```

判定：编译失败 → 整个 Phase 0 标记 FAIL，记录错误信息，停止后续阶段。

### 0.2 安全模式扫描

用 Grep 工具扫描以下高风险模式：

| 扫描项 | 正则模式 | 级别 |
|--------|----------|------|
| SQL 拼接 | `"SELECT.*"\s*\+\|"INSERT.*"\s*\+\|"UPDATE.*"\s*\+\|"DELETE.*"\s*\+` | Critical |
| System.out 残留 | `System\.out\.print` | Major |
| 硬编码密码 | `password\s*=\s*"[^"]+"\|passwd\s*=\s*"[^"]+"` | Critical |
| 硬编码 IP/端口 | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+` | Major |
| 敏感信息日志 | `log\.\w+\(.*password\|log\.\w+\(.*token\|log\.\w+\(.*secret` | Critical |
| TODO/FIXME 残留 | `TODO\|FIXME\|HACK\|XXX` | Minor |

### 0.3 Import/依赖检查

```
- 扫描 Java 文件中的 unused import（import 了但文件中未使用对应类名）
- 检查 @Resource/@Autowired 注入的 bean 是否在 Dubbo/Spring 配置中有声明
- 检查 pom.xml 变更：新增依赖是否指定版本号，是否引入冲突
```

### 0.4 Phase 0 产出

```markdown
## Phase 0: 自动化验证结果

| 检查项 | 状态 | 发现数 | 详情 |
|--------|------|--------|------|
| 编译检查 | PASS/FAIL | - | {错误信息或"编译成功"} |
| SQL 拼接 | PASS/FAIL | {n} | {文件:行号 列表} |
| System.out 残留 | PASS/FAIL | {n} | {文件:行号 列表} |
| 硬编码密码 | PASS/FAIL | {n} | {文件:行号 列表} |
| 敏感信息日志 | PASS/FAIL | {n} | {文件:行号 列表} |
| Import/依赖 | PASS/FAIL | {n} | {问题列表} |

Phase 0 结论: PASS / FAIL (Critical: {n}, Major: {n}, Minor: {n})
```

如果 Phase 0 有 Critical 问题 → 提示修复后重跑 Phase 0（进入自动修复循环）。

---

## Phase 1: Spec 符合性检查

**目标：对照 spec.md、contracts.md、testcases.md 逐条核对需求实现的完整性和正确性。**

### 1.1 需求目标核对

读取 spec.md 第 1 章「需求」，逐个 G-xxx 目标检查：

```
对于每个 G-xxx:
  1. 代码中是否有对应实现？（定位到具体文件和方法）
  2. 实现的行为是否与目标描述一致？
  3. 边界条件和异常路径是否考虑？
```

### 1.2 接口契约核对

读取 contracts.md，逐个 API-xxx 接口检查：

| 检查维度 | 具体验证项 |
|----------|-----------|
| 入参 | 类型、名称、必填/选填是否与 spec 一致 |
| 出参 | 返回类型、字段结构是否与 spec 一致 |
| 行为 | 核心逻辑是否与 spec 描述匹配（重点） |
| 错误码 | 异常情况是否返回约定的错误码 |

### 1.3 数据变更核对

读取 design.md「数据变更」：

```
- DDL 脚本是否已准备？与 spec 定义一致？
- 索引是否已定义？
- 数据迁移脚本是否需要？是否可逆？
```

### 1.4 追溯矩阵覆盖

读取 spec.md 第 5 章「追溯矩阵」，检查追溯覆盖：

```
- 每条需求 → 是否有对应的测试用例？
- 每条测试用例 → 是否有对应的代码实现？
- 覆盖率统计：已覆盖/总数 = {x}%
```

### 1.5 部署计划完整性

```
- 部署顺序是否明确？（API 先部署还是服务先部署）
- 配置变更是否列出？（Nacos/SuperDiamond）
- 数据库变更是否有执行顺序？
- 回滚方案是否明确？
```

### 1.6 Phase 1 产出

```markdown
## Phase 1: Spec 符合性检查结果

### 需求目标
| 目标 ID | 目标描述 | 状态 | 实现位置 | 说明 |
|---------|---------|------|---------|------|

### 接口契约
| 接口 ID | 入参 | 出参 | 行为 | 状态 | 说明 |
|---------|------|------|------|------|------|

### 追溯覆盖
| 需求 | 测试覆盖 | 代码实现 | 状态 |
|------|---------|---------|------|

覆盖率: {x}%
Phase 1 结论: PASS / FAIL
```

---

## Phase 2: 代码质量深度检查

**目标：结合编码规范、检查点清单和项目踩坑记录做深层质量审查。**

### 2.1 架构层面

| 检查项 | 说明 |
|--------|------|
| 分层违反 | Controller 直接访问 DAO？Service 层调用 Controller？ |
| 循环依赖 | A 依赖 B，B 又依赖 A（Dubbo 接口层面或 Spring Bean 层面） |
| RPC 使用规范 | 接口定义在 api 模块？DTO 是否实现 Serializable？版本号是否正确？ |
| 注入规范 | 项目约定的注入方式是否一致？（参考 CLAUDE.md 编码规范） |
| 多仓库同步 | 改了一处是否需要同步改另一处？（参考 CLAUDE.md 踩坑记录） |

### 2.2 数据访问层面

| 检查项 | 说明 |
|--------|------|
| SQL 注入 | 字符串拼接 SQL（Phase 0 已扫描，此处深度确认） |
| 事务边界 | 多表写操作是否在同一事务内？@Transactional 是否在正确位置？ |
| N+1 查询 | 循环中执行 SQL 查询？应批量查询 |
| 分页缺失 | 查询是否有 LIMIT？大表全表扫描风险 |
| ORM 混用 | 同一业务逻辑中混用多种数据访问方式的事务一致性 |

### 2.3 安全层面

| 检查项 | 说明 |
|--------|------|
| 认证绕过 | 接口是否有 Token/Session 校验？ |
| 授权缺陷 | 权限检查是否完整？（参考 CLAUDE.md 中已知的权限漏洞模式） |
| XSS 风险 | 用户输入是否转义后输出？ |
| 敏感数据 | 密码/Token 是否明文存储或日志输出？ |
| SSRF 风险 | 外部 URL 请求是否做了白名单校验？ |

### 2.4 错误处理

| 检查项 | 说明 |
|--------|------|
| 吞异常 | catch 块中空处理或只 log 不处理？ |
| 泛化 catch | catch(Exception e) 吞掉所有异常？ |
| 事务回滚 | 异常时 @Transactional 是否正确回滚？（默认只回滚 RuntimeException） |
| 资源泄漏 | IO/Connection 是否在 finally 中关闭？ |

### 2.5 并发与性能

| 检查项 | 说明 |
|--------|------|
| 共享可变状态 | 成员变量在多线程环境下是否安全？ |
| 缺少同步 | 并发操作共享资源未加锁？ |
| 连接池 | 数据库/Redis 连接是否通过池管理？ |
| 无界查询 | 查询条件缺失导致返回大量数据？ |
| 过度日志 | 高频调用路径上的 debug/info 日志？ |

### 2.6 业务逻辑

| 检查项 | 说明 |
|--------|------|
| 角色权限 | 角色判断是否使用正确的枚举值？（参考 CLAUDE.md 角色体系） |
| 业务场景区分 | 是否区分了不同业务场景的处理逻辑？ |
| 数据一致性 | 多仓库/多模块间的数据是否一致？ |
| API 向后兼容 | 接口变更是否会影响已有调用方？ |
| 数据库迁移可逆 | DDL 变更是否可回滚？ |

### 2.7 编码规范（from conventions.md）

从项目 CLAUDE.md 的 `## 编码规范` 章节读取，包含：包命名规范、JSON 库选择、响应包装类型、注入方式等项目特定约定。

### 2.8 143 检查点清单引用

读取 `references/代码设计与实现阶段checklist.md`（如果存在），根据改动涉及的模块筛选相关检查项：

| 模块 | 检查点范围 | 触发条件 |
|------|-----------|----------|
| 登录认证 | 序号 1-23 | 改动涉及 Token/Session/认证逻辑 |
| 列表操作 | 序号 24-45 | 改动涉及分页查询/列表展示 |
| 上传导入 | 序号 49-52 | 改动涉及文件上传/数据导入 |
| 缓存使用 | 序号 53-70 | 改动涉及 Redis/缓存操作 |
| 支付功能 | 序号 103-107 | 改动涉及支付/金额计算 |
| 其他模块 | 按实际匹配 | 根据改动内容动态筛选 |

### 2.9 Phase 2 产出

按问题级别分组输出，每个问题包含：

```markdown
### {级别}-{序号}: {问题标题}

**类型**: {架构/数据访问/安全/错误处理/并发/业务/规范}
**位置**: `{文件路径}:{行号}`
**风险**: {Critical/Major/Minor}

**问题描述**:
{具体描述}

**问题代码**:
{代码片段}

**修复建议**:
{具体修复方案或代码}
```

---

## 自动修复循环

当审查发现可修复的问题时，执行自动修复循环：

```
ROUND = 0
MAX_ROUNDS = 3

while ROUND < MAX_ROUNDS:
    findings = run_review_phase(failed_phase)
    fixable = [f for f in findings if f.auto_fixable]

    if not fixable:
        break

    提示用户: "发现 {n} 个可自动修复的问题，是否执行？(Y/N)"
    if Y:
        apply_fixes(fixable)
        ROUND += 1
        重跑失败的 Phase
    else:
        break

if ROUND == MAX_ROUNDS and still_has_issues:
    提示: "已达最大自动修复轮次(3轮)，剩余问题需人工处理"
```

**可自动修复的问题类型：**
- System.out.println → 替换为 log.info/debug
- unused import → 删除
- 缺少 @Override → 添加
- 硬编码字符串 → 提取为常量
- 空 catch 块 → 添加 log.error

---

## 最终产出

写入 `.ai-workspace/review/findings.md`：

```markdown
# Review 结果

> 审查时间: {时间} | 结论: APPROVED / REJECTED
> 审查轮次: {round} | 自动修复: {fix_count} 项

## 总览

| 阶段 | 状态 | Critical | Major | Minor |
|------|------|----------|-------|-------|
| Phase 0: 自动化验证 | PASS/FAIL | {n} | {n} | {n} |
| Phase 1: Spec 符合性 | PASS/FAIL | {n} | {n} | {n} |
| Phase 2: 代码质量 | PASS/FAIL | {n} | {n} | {n} |
| **合计** | **{结论}** | **{n}** | **{n}** | **{n}** |

## Phase 0: 自动化验证
{Phase 0 产出内容}

## Phase 1: Spec 符合性检查
{Phase 1 产出内容}

## Phase 2: 代码质量深度检查
{Phase 2 产出内容}

## 自动修复记录
| 轮次 | 修复项 | 文件 | 状态 |
|------|--------|------|------|
```

---

## 完成动作

1. 沉淀 review 发现的模式 → ~/knowledge-base/insights/platform/（代码规范、安全模式、踩坑记录）
3. 结论判定：
   - **APPROVED**: 所有阶段 PASS，无 Critical/Major 未修复问题
   - **REJECTED**: 存在未修复的 Critical 或 Major 问题
4. 通过时提示：`review 阶段完成，下一步: /testing`
5. 不通过时提示：`review 未通过，{n} 个问题待修复。修复后重新 /review`

---

## 产出物

| 文件 | 路径 | 用途 |
|------|------|------|
| findings.md | .ai-workspace/review/findings.md | 审查结果 |

## 危险信号

**绝不要：**
- develop 未完成就开始 review
- 跳过 Phase 0 直接做人工审查
- 只看代码风格不看 Spec 符合性
- 发现 Critical 问题后仍标记为 APPROVED
- 只提问题不给修复建议
- 自动修复超过 3 轮还继续

**始终要：**
- Phase 0 先跑自动化，排除低级问题
- 对照 spec.md、contracts.md、testcases.md 逐条核对
- 检查追溯矩阵完整性
- 每个问题标注级别和修复建议
- 利用知识库中的规范和踩坑记录
- 关注多仓库代码同步问题（参考 CLAUDE.md）
- 关注 CLAUDE.md 中记录的已知漏洞模式
