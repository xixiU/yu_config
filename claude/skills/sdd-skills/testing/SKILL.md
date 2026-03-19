---
name: testing
description: 从代码到验证的完整交付闭环。五个阶段全自动执行：代码提交/PR → 构建部署(依赖排序+版本传播) → 自动化测试 → 结果报告 → 交付归档。
---

# 从代码到验证（Ship It）

## 概述

合并原 testing / deliver / deploy / build-deploy 四个技能为一站式 CI/CD/QA 交付闭环。用户输入 `/testing`，自动驱动 CI（代码提交）→ CI/CD（构建部署）→ QA（自动化测试）→ Report（结果报告）→ Deliver（交付归档）全流程。

**五个阶段（CI/CD/QA 流水线）：**
1. **Phase 1: CI** — 代码提交与 PR 创建
2. **Phase 2: CI/CD** — 构建部署（依赖排序 + API 版本传播 + iPipeline 自动化）
3. **Phase 3: QA** — 自动化测试（API + E2E + DB 验证）
4. **Phase 4: Report** — 结果处理与报告
5. **Phase 5: Deliver** — 交付归档与经验沉淀

**核心理念：**
1. 全自动 — 用户只输入 `/testing`，其余全部自动
2. SSO 统一认证 — 通过 `IFLYTEK_SSO_USERNAME` / `IFLYTEK_SSO_PASSWORD` 环境变量自动登录
3. Spec 驱动 — 测试用例从 testcases.md、接口契约从 contracts.md、构建顺序从 tasks.md 读取
4. 依赖感知 — API 必须先于消费方构建，版本自动传播
5. 失败才停 — 构建失败、测试不过才暂停让用户处理

## 铁律

```
1. spec.md 必须存在且已审批
2. review 必须通过（findings.md 结论为 APPROVED）才能执行
3. 构建顺序严格遵循依赖图：API 先于消费方，绝不跳过
4. API 版本传播必须完成且提交后才能构建消费方
5. 未执行的测试用例不得标记为 PASS — 没有捷径，每条用例都要真正执行
6. 每个 E2E 测试用例必须有截图证据 — 同一张截图不得复用给多条用例
7. 所有 P1 级别测试用例必须通过，整体才算 PASS
8. 绝不部署到生产环境
9. 组件清单必须按"组件名称 / Git仓库 / Feature分支"格式总结
10. 每个功能点至少 8-15 条测试用例，正反比约 4:6
11. 用例字段 9 个全填，不允许为空
12. SKIP 用例的 error 字段必填，写明具体跳过原因
```

**违反这些规则的字面意思就是违反这些规则的精神。**

## 前置条件

<HARD-GATE>
1. `.ai-workspace/review/findings.md` 存在且结论为 APPROVED
2. spec.md 存在且已审批
3. `IFLYTEK_SSO_USERNAME` 和 `IFLYTEK_SSO_PASSWORD` 环境变量存在（密码为 base64 编码）
4. `playwright-cli --version` 可用
</HARD-GATE>

## 凭证管理

启动时检测必要配置，缺失时向用户询问：

| 缺失项 | 行为 |
|--------|------|
| 测试环境地址 | 询问用户 |
| 测试账号密码 | 询问用户（角色/用户名/密码） |
| 质效平台地址 | 询问用户 |
| SSO 账密 | 环境变量 `IFLYTEK_SSO_USERNAME` / `IFLYTEK_SSO_PASSWORD`（密码 base64 编码） |

SSO 环境变量为必填项，缺失则立即停止并提示用户配置。测试环境地址、测试账号等信息通过 Auto Memory 保存复用。

---

## Phase 1: CI — 代码提交与 PR 创建

### 1.1 交付前验证 + 变更检测

读取 `.ai-workspace/repos.md` 获取 worktree 清单，对每个 worktree：

```bash
cd {worktree路径}
git status                                    # 工作区干净
git fetch origin
git merge-base --is-ancestor origin/{目标分支} HEAD  # 无冲突
git diff master...HEAD --name-only --stat     # 变更检测
```

需要 rebase 时：执行 rebase → 重新运行测试 → 通过后继续。
**只有实际有变更的组件才会构建部署，无变更的跳过。**

### 1.2 提交代码

对每个有变更的 worktree：

```bash
cd {worktree路径}
git add -A
git commit -m "feat({模块}): {spec.md中的需求标题}"
git push -u origin {分支名}
```

### 1.3 创建 PR

为每个仓库创建 Pull Request：

```bash
gh pr create --title "{需求编号}: {简短描述}" --body "{PR描述}" --base develop
```

PR 描述从 spec.md + contracts.md 自动生成，包含：摘要（2-3 要点）、需求背景、变更内容（按模块）、测试情况 checklist、受影响模块、部署注意事项。

### 1.4 HARD-GATE: 等待 PR 确认

<HARD-GATE>
所有仓库的 PR 创建完成后，暂停并询问用户：

"所有 PR 已创建完成，请确认 PR 审批通过后继续构建部署。PR 链接如下：
{逐个列出 PR URL}

PR 是否都已审批通过？"

用户确认后才进入 Phase 2。
</HARD-GATE>

---

## Phase 2: CI/CD — 构建与部署

### 2.1 加载部署上下文

读取 tasks.md 第3章（构建部署顺序）、~/knowledge-base/dependencies.md（依赖图）、repos.md（组件清单）。

### 2.2 构建顺序编排

从 tasks.md 第3章或 ~/knowledge-base/dependencies.md 读取依赖关系，结合变更检测，生成构建计划：

```
| 序号 | 组件名 | 分支 | 质效地址 | 批次 | 操作 |
|------|--------|------|---------|------|------|
| 1 | {api模块} | feature/xxx | {质效平台地址}/appId=A001 | Batch 1 | 仅构建(mvn deploy) |
| 2 | {service模块} | feature/xxx | {质效平台地址}/appId=A002 | Batch 2 | 构建+部署[test] |
| 3 | {web模块} | feature/xxx | {质效平台地址}/appId=A003 | Batch 3 | 构建+部署[test] |

依赖关系：#1 → 版本传播 → #2, #3
```

**与用户确认构建计划后执行。** 同时检查本地与远端分支差异，存在差异时询问用户。

### 2.3 执行构建（逐批次）

对每个批次中的组件调用 `build_and_deploy.py`（端到端自包含脚本：浏览器 → SSO 登录 → 构建 → 部署 → 输出 JSON）：

```bash
# Bash 参数：run_in_background=true, timeout=600000
python {SKILL_DIR}/scripts/build_and_deploy.py \
  --url "{质效地址}" \
  --branch "{feature分支}" \
  --env "{目标环境}" \
  --session deploy-{组件名}
```

<IMPORTANT>
**必须使用 `run_in_background: true`。** 构建部署通常需要 5-20 分钟，启动后立即告知用户："构建已在后台启动（任务 ID: {id}），你可以继续做其他事。"
</IMPORTANT>

**同一批次的组件并行构建**（每个启动一个后台任务）。
**批次间串行**（等前一批全部成功后再启动下一批）。

### 2.4 API 版本传播（关键）

当 API 模块构建成功后，**自动完成版本传播**：

```
1. 从构建结果 JSON 提取新版本号（如 1.2.4-SNAPSHOT）
2. 查找所有消费方组件（从 ~/knowledge-base/dependencies.md 或 tasks.md）
3. 对每个消费方：
   a. 定位 pom.xml 中的版本属性（如 <pt-api.version>）
   b. 更新版本号
   c. git add pom.xml && git commit -m "chore: update {包名} version to {新版本}"
   d. git push
4. 然后才触发消费方的构建
```

<HARD-GATE>
版本传播完成后暂停："下游依赖版本已更新并推送，PR 已自动更新。请确认 PR 审批通过后继续。"
用户确认后才继续构建下游项目。
</HARD-GATE>

### 2.5 构建消费方 + deploy-only 模式

版本传播完成后，按批次构建消费方组件，流程同 2.3。跳过构建直接部署：加 `--deploy-only "{版本号}"` 参数。

### 2.6 健康检查

部署完成后验证服务正常启动：

```bash
curl -s -o /dev/null -w "%{http_code}" http://{服务地址}/actuator/health  # 后端
curl -s -o /dev/null -w "%{http_code}" http://{前端地址}/                  # 前端
```

失败处理：等待 30 秒重试，最多 3 次。仍然失败 → 标记"部署异常"，提供回滚选项：
1. 回滚到上一版本（`--deploy-only "{上一版本号}"`）
2. 暂不回滚，排查问题（提供日志查看指引）
3. 部分回滚（只回滚失败的组件）

任何构建/部署失败 → 停下来，展示错误信息，等用户处理。

---

## Phase 3: QA — 自动化测试

### 3.1 加载测试用例

读取 `.ai-workspace/testcases.md`（/spec Phase 4 已生成），作为执行依据。

> 测试用例的生成规范和设计方法在 /spec 中定义，/testing 不再生成用例。

### 3.2 测试环境准备

```
1. 获取测试环境 URL + 测试账号（从 Auto Memory 或询问用户）
2. 读取 testcases.md + contracts.md 接口契约
4. 创建截图目录：.ai-workspace/testing/screenshots/
5. 确认 playwright-cli 可用：playwright-cli --version
6. 清理全部残留会话：playwright-cli session-stop-all
```

> `--config` 只在创建新 daemon 时生效。残留 daemon 会忽略新的 `--config`，导致 Cookie 隔离失效。

### 3.3 执行模式选择

| 用例总数 | 执行模式 |
|---------|---------|
| **< 50 条** | **单人模式**：直接使用 `playwright-cli --session agent1` 执行全部用例 |
| **≥ 50 条** | **并行模式**：Agent Teams 3人并行，按账号分组 |

#### 单人模式（用例数 < 50）

直接使用 `playwright-cli --session agent1` 执行全部用例。涉及多账号时，每次切换账号先 `session-stop` 再重新 `open`。

#### 并行模式（用例数 ≥ 50）

使用 Agent Teams 开启3个测试人员并行执行。

**用例分配原则：按账号分组，同一账号的用例分配给同一 Agent，避免多 Agent 同时操作同一账号。**

**Lead Agent 职责：**
1. 按测试账号对用例分组，将账号组均分给 3 个 Agent
2. 创建 Agent Teams，spawn 3 个测试人员，传入各自的账号组及对应用例
3. 每隔 10 分钟向各 Agent 发消息询问进度，汇总输出
4. 等待全部完成，合并结果写入 `.ai-workspace/testing/test-results.json`

**各测试人员职责：** 按账号逐个执行用例。切换账号时先 `session-stop` 再重新 `open`，确保每个账号在全新 BrowserContext 中运行。

### 3.4 浏览器启动与 Cookie 隔离

<HARD-GATE>
并行模式（多 Agent 同时测试同一域名）**必须**使用 `isolated: true` 配置。
不使用 isolated 模式**将**导致 Cookie 跨 Agent 污染，测试结果不可信。
</HARD-GATE>

**问题根因：** playwright-cli 默认使用持久化上下文（`launchPersistentContext`），所有 session 共享同一个 `userDataDir`。多 Agent 同时访问同一域名并设置 Cookie 时，Cookie 相互覆盖。

> **`--profile` 不是 playwright-cli 的有效选项，会被静默忽略。禁止使用。**
>
> **`-s=agentN` 不是 `--session agentN` 的有效缩写。** playwright-cli 使用 minimist 解析参数，未定义 `-s` 为 `--session` 的别名。`-s=agent1` 会回退到 `default` session，导致 cookie 污染。**必须使用完整的 `--session agentN` 语法。**

**解决方案：`isolated: true`**

`isolated: true` 使每个 session 通过 `browser.newContext()` 创建独立的 BrowserContext，拥有独立的 Cookie 存储。

**配置文件生成（Lead Agent 在分派前执行）：**

```bash
mkdir -p .ai-workspace/testing/configs
for i in 1 2 3; do
cat > .ai-workspace/testing/configs/agent${i}.json << 'EOF'
{
  "browser": {
    "browserName": "chromium",
    "isolated": true,
    "launchOptions": { "channel": "chrome", "headless": false },
    "contextOptions": { "viewport": null }
  }
}
EOF
done
```

**启动浏览器：**

```bash
playwright-cli --session agent1 --config=.ai-workspace/testing/configs/agent1.json open {URL}
playwright-cli --session agent1 snapshot
```

**账号切换流程（必须 `session-stop`，不是 `close`）：**

```bash
# 1. 停止会话（彻底销毁 BrowserContext、Cookie、LocalStorage）
playwright-cli session-stop agent1

# 2. 重新启动（全新 BrowserContext，零 Cookie）
playwright-cli --session agent1 --config=.ai-workspace/testing/configs/agent1.json open {URL}

# 3. 执行新账号的认证
```

> `session-stop` vs `close`：`close` 仅关闭页面标签，BrowserContext 和 Cookie 仍存活。`session-stop` 终止守护进程，销毁整个 BrowserContext。

### 3.5 身份认证策略

**方案A：page.goto 直接获取 Cookie（推荐，isolated 模式下安全）**

```bash
# 获取 token
playwright-cli --session agent1 run-code "async page => {
  const resp = await page.request.get('https://hwtest.zhixue.com/hw/tools/token/value?secret=xxx&userId=${userId}');
  const token = await resp.text();
  console.log('TOKEN:', token);
}"

# 用 page.goto 换取 Cookie（isolated 模式下安全）
playwright-cli --session agent1 run-code "async page => {
  await page.goto('https://test.zhixue.com/container/app/token/getCookie?token=${TOKEN}&secret=xxx');
  await page.waitForTimeout(2000);
  const cookies = await page.context().cookies('https://test.zhixue.com');
  console.log('Cookies set:', cookies.map(c => c.name).join(', '));
}"

# 导航到目标页面
playwright-cli --session agent1 run-code "async page => { await page.goto('${TARGET_URL}'); await page.waitForTimeout(3000); }"

# 验证认证成功 + Cookie 污染检查
playwright-cli --session agent1 snapshot
# ⚠ 检查页面上显示的用户名是否与当前测试账号一致
```

**方案B：curl + addCookies（兜底，不依赖 isolated 模式）**

```bash
TOKEN=$(curl -s 'https://hwtest.zhixue.com/hw/tools/token/value?secret=xxx&userId=${userId}')
curl -s -D - -o /dev/null "https://test.zhixue.com/container/app/token/getCookie?token=$TOKEN&secret=xxx" | grep -i '^Set-Cookie:'

playwright-cli --session agent1 --config=.ai-workspace/testing/configs/agent1.json open {BASE_URL}
playwright-cli --session agent1 run-code "async page => {
  await page.context().clearCookies();
  await page.context().addCookies([
    { name: 'tlsysSessionId', value: 'abc123', domain: '.zhixue.com', path: '/' }
  ]);
}"
```

**方案C：UI 登录流程（通用兜底）**

```bash
# Lead Agent：为每个账号登录并保存状态
playwright-cli --session setup --config=.ai-workspace/testing/configs/agent1.json open {LOGIN_URL}
playwright-cli --session setup snapshot
playwright-cli --session setup fill {ref} "username"
playwright-cli --session setup fill {ref} "password"
playwright-cli --session setup click {ref}
playwright-cli --session setup run-code "async page => {
  await page.waitForTimeout(2000);
  const state = await page.context().storageState();
  require('fs').writeFileSync('.ai-workspace/testing/auth-${userId}.json', JSON.stringify(state, null, 2));
}"
playwright-cli session-stop setup

# 测试人员：加载认证状态
playwright-cli --session agent1 --config=.ai-workspace/testing/configs/agent1.json open {BASE_URL}
playwright-cli --session agent1 run-code "async page => {
  const state = JSON.parse(require('fs').readFileSync('.ai-workspace/testing/auth-${userId}.json', 'utf8'));
  await page.context().clearCookies();
  if (state.cookies?.length > 0) await page.context().addCookies(state.cookies);
}"
```

**Cookie 污染验证（并行模式下，每次认证后必须执行）：**

1. 执行 `snapshot`，查看页面上显示的用户名/账号
2. 与当前测试账号比对
3. 不一致 → Cookie 污染确认 → `session-stop` → 重新 open + 认证 → 再次验证
4. 反复污染 → 检查是否遗忘 `--config` 参数 → 最后手段：降级为串行模式

### 3.6 接口级测试

读取 type=unit 或 type=integration 的测试用例：

```
对每条接口测试用例（关联 TC-xxx ID）：
  1. 从 contracts.md 定位 API 端点
  2. 构造请求（URL、Method、Headers、Body）
  3. 发送请求
  4. 对比：期望结果 vs 实际结果 → PASS / FAIL
  5. 记录响应时间、状态码、响应体
```

### 3.7 E2E 测试

**标准执行流程（每条用例）：**

```bash
# 1. 导航到目标页面
playwright-cli --session agentN goto {TARGET_URL}

# 2. 获取元素引用（交互前必须执行）
playwright-cli --session agentN snapshot

# 3. 按步骤操作
playwright-cli --session agentN click {ref}
playwright-cli --session agentN fill {ref} "value"
playwright-cli --session agentN select {ref} "option"
playwright-cli --session agentN press Enter

# 4. 等待加载完成
playwright-cli --session agentN run-code "async page => await page.waitForTimeout(1000)"

# 5. 验证结果状态
playwright-cli --session agentN snapshot

# 6. 截图（每条用例独立）
playwright-cli --session agentN screenshot --filename=.ai-workspace/testing/screenshots/{TC-ID}.png

# 7. 判定：预期结果全部满足 → PASS；任一不满足 → FAIL（记录差异）
```

**批量执行策略（高效模式）：** 同一页面/弹窗内有多个相关用例时，可减少命令调用：

| 情形 | 推荐方式 |
|------|---------|
| 同一弹窗内多个输入验证 | **批量**：打开弹窗一次，单次 `run-code` 完成所有断言 |
| 同一区域多个样式/颜色检查 | **批量**：单次 `run-code` JS 一并查询 |
| 同一页面多个数据统计核查 | **批量**：单次 `run-code` 一并提取 |
| 跨页面导航 | 标准流程 |

**批量规则：** 截图不可省（每条用例仍须独立截图）；操作仍须按用例顺序；结果必须精确对应每条用例。

**执行规则：**
- 交互前必须执行 `snapshot` — 导航后元素引用会失效
- 逐条执行、逐条截图 — 硬性要求
- 失败隔离：用例失败时记录错误 + 截图，继续执行下一条

### 3.8 数据库验证（可选）

如果用户提供了数据库连接信息：
1. 连接测试数据库
2. 验证 DDL 变更是否生效（索引、表结构）
3. 验证关键数据一致性
4. 跳过条件：无数据库配置或用户主动跳过

### 3.9 SKIP 用例规则

仅在以下不可抗因素下允许标记 SKIP：
- **功能未部署**：目标功能在当前环境未上线
- **测试数据不可得**：需要特殊前置数据且无法构造
- **环境限制**：需要特定条件，当前工具无法模拟
- **阻塞性缺陷**：前置步骤存在已知 BUG

**SKIP 字段填写规范：**
- `error` 字段：**必填**，写明具体的跳过原因，不允许留空或填 `null`
- `notes` 字段：仅记录额外观察，不得将跳过原因写在此处

### 3.10 执行结果 JSON 格式

所有用例执行完毕后，汇总写入 `.ai-workspace/testing/test-results.json`：

```json
{
  "results": [
    {
      "id": "TC-XKXQ-0001",
      "module": "模块名称",
      "name": "测试用例标题",
      "priority": "P1",
      "status": "PASS | FAIL | SKIP",
      "screenshot": "screenshots/TC-XKXQ-0001.png",
      "error": null,
      "notes": "观察备注"
    }
  ]
}
```

字段要求：
- `screenshot`：**必填**，每条用例独立截图
- `error`：FAIL 填差异；SKIP 必须填具体原因；PASS 为 null
- `notes`：仅记录额外观察，不放跳过原因

### 3.11 测试失败处理

如果有 P1 级别用例失败：
1. 展示失败用例列表和可能原因
2. 提示："是否自动修复并重新测试？(Y/N)"
   - Y → 分析失败原因 → 修复代码 → 重新从 Phase 1 执行
   - N → 用户手动处理，流程暂停

**判定规则：**
- 所有 P1 用例必须通过 → 整体才算 PASS
- P2+ 失败不阻塞，但记录在报告中分析

---

## Phase 4: Report — 结果与报告

### 4.1 生成测试报告

写入 `.ai-workspace/testing/report.md`：

```markdown
# 测试报告

> 需求: {需求标题} | 时间: {timestamp}

## 构建状态

| 组件 | 批次 | 构建状态 | 版本号 | 耗时 |
|------|------|----------|--------|------|
| {api模块} | 1 | 成功 | 1.2.4-SNAPSHOT | 5m |

## 部署状态

| 组件 | 环境 | 部署状态 | 健康检查 |
|------|------|----------|----------|
| {service模块} | test | 成功 | 200 OK |

## 版本传播记录

| 上游组件 | 新版本 | 下游组件 | 更新属性 |
|----------|--------|----------|----------|
| {api模块} | 1.2.4-SNAPSHOT | {service模块} | {api.version属性} |

## 测试结果

| 总计 | 通过 | 失败 | 跳过 |
|------|------|------|------|

### 详细结果

| ID | 级别 | 标题 | 类型 | 结果 | 截图 |
|----|------|------|------|------|------|
| TC-001 | P1 | xxx | API | PASS | - |
| TC-002 | P1 | xxx | E2E | PASS | screenshots/TC-002-step1.png |

## PR 链接

| 仓库 | PR URL | 分支 |
|------|--------|------|

## 组件清单

| 组件名称 | Git仓库 | Feature分支 |
|----------|---------|-------------|
```

### 4.2 生成测试报告

将测试结果汇总到 `.ai-workspace/testing/report.md`。

---

## Phase 5: Deliver — 交付归档

### 5.1 撰写交付记录

写入 `.ai-workspace/deliver/record.md`：日期、PR 链接、分支信息、质量关卡通过情况、部署信息（环境/状态/版本号/时间）、变更摘要、人工关注事项。

### 5.2 向用户展示交付摘要

展示交付摘要（不修改 CLAUDE.md，CLAUDE.md 由用户自行维护）：
- 交付摘要：

```markdown
## 快速开始

流水线已完成。

交付记录：`.ai-workspace/deliver/record.md`
PR 链接：{PR 链接}

相关文档：
- 需求规约：`.ai-workspace/spec.md`
- 开发进度：`.ai-workspace/develop/progress.md`
- 评审报告：`.ai-workspace/review/findings.md`
- 测试报告：`.ai-workspace/testing/report.md`
- 交付记录：`.ai-workspace/deliver/record.md`
```

### 5.3 经验沉淀

1. 测试暴露的边界 case → ~/knowledge-base/insights/platform/
2. 构建部署新发现 → ~/knowledge-base/pitfalls.md
3. 更新 ~/knowledge-base/dependencies.md（如依赖关系有变）
4. 沉淀本次经验到 ~/knowledge-base/insights/（踩坑记录、构建部署经验等）

### 5.4 组件清单总结

**必须输出改动的组件清单（质效平台维度）：**

```
| 组件名称 | Git仓库 | Feature分支 |
|----------|---------|-------------|
| {api模块名} | {Git仓库路径} | feature/{需求分支} |
| {service模块名} | {Git仓库路径} | feature/{需求分支} |
| {web模块名} | {Git仓库路径} | feature/{需求分支} |
```

同步更新到 `.ai-workspace/repos.md` 的"组件清单"章节。

### 5.5 Worktree 清理（可选，需用户确认）

提示用户选择：清理所有 worktree（`git worktree remove`）或保留。清理后更新 repos.md。

### 5.6 通知（可选）

尝试调用 `/feishu notify --template "deploy-done"`，失败不阻塞。

---

## 独立使用模式

不在流水线中时，也可以部分使用：

```
/testing                              # 全流程：提交 → 构建 → 测试 → 归档
/testing --phase build                # 只执行 Phase 2（构建部署）
/testing --phase test                 # 只执行 Phase 3（自动化测试）
/testing --component srv-pt-api       # 只构建指定组件
/testing --env dev                    # 指定目标环境（默认 test）
/testing --deploy-only "1.2.3"        # 跳过构建，直接部署指定版本
/testing --rollback srv-pt-api        # 回滚指定组件到上一版本
/testing --skip-check                 # 跳过评审/测试前置检查
```

---

## 产出物总览

| 文件 | 路径 | 用途 |
|------|------|------|
| test-results.json | .ai-workspace/testing/test-results.json | 执行结果（JSON 格式） |
| report.md | .ai-workspace/testing/report.md | 测试报告（含构建+部署+测试结果） |
| record.md | .ai-workspace/deliver/record.md | 交付记录 |
| screenshots/ | .ai-workspace/testing/screenshots/ | E2E 截图证据 |
| PR | Git 平台 | 代码合并请求 |
| 知识库更新 | ~/knowledge-base/ | 经验沉淀 |

## 集成

**从工作区读取：**
- `.ai-workspace/review/findings.md` — 评审报告（前置检查）
- `.ai-workspace/spec.md` — 需求 + 风险评估 + 追溯矩阵
- `.ai-workspace/contracts.md` — 接口契约
- `.ai-workspace/testcases.md` — 验收标准 + 测试用例
- `.ai-workspace/develop/progress.md` — 开发进度（用于变更列表）
- `.ai-workspace/repos.md` — worktree 清单 + 部署配置（项目名、Git 地址、质效地址、环境）
- `.ai-workspace/tasks.md` — 构建部署顺序 + 回滚策略
- `~/knowledge-base/dependencies.md` — 服务依赖关系
- Auto Memory — 测试环境 URL + 账号 + 质效平台地址

**写入工作区：**
- `.ai-workspace/testing/report.md` — 测试报告
- `.ai-workspace/testing/screenshots/` — E2E 截图
- `.ai-workspace/deliver/record.md` — 交付记录

**整体流程：**
`/spec` → `/develop` → `/review` → **`/testing`**

本 skill 是流水线的最后一个环节，合并了原 testing + deliver + deploy + build-deploy 四个技能。

## 危险信号

**绝不要：**
- review 未通过就开始执行
- 在生产环境执行测试或部署
- 跳过 API 版本传播直接构建消费方
- 跳过构建顺序直接部署
- 未执行的用例标记为 PASS
- 同一张截图复用给多条用例
- 用探索性测试结果批量推断
- 在 build_and_deploy.py 外部执行 `playwright-cli` 命令（会导致 pipe 冲突）
- 不确认构建计划就执行
- 构建失败后不报告继续下一批
- 并行模式下不带 `--config` 启动浏览器（导致 Cookie 污染）
- 使用 `--profile` 参数（无效选项，被静默忽略）
- 使用 `-s=agentN` 代替 `--session agentN`（`-s` 不是有效缩写，回退到 default session）
- 用 `close` 代替 `session-stop` 切换账号（Cookie 残留）

**始终要：**
- 先检测 `IFLYTEK_SSO_USERNAME` / `IFLYTEK_SSO_PASSWORD` 环境变量
- 逐条执行、逐条截图
- SKIP 用例必须写明具体原因
- 失败时记录实际结果与预期的差异
- 只构建有变更的组件，不做无意义的全量构建
- 严格按依赖图的构建顺序执行
- API 先于消费方，版本传播后先提交再构建
- 并行模式下每次 `open` 都带 `--config=.../agentN.json`（含 `isolated: true`）
- 认证后立即验证页面用户名（Cookie 污染检测）
- 切换账号时使用 `session-stop`（不是 `close`）
- 输出组件清单表格

## 常见自我合理化

| 借口 | 现实 |
|------|------|
| "review 通过了肯定没问题" | review 检查代码质量，不等于运行时正确 |
| "刚才测试通过了，不用再跑了" | rebase 后可能引入新问题 |
| "只是小改动，不需要完整 PR 描述" | PR 描述是给评审者看的，不是给自己看的 |
| "部署配置我大概知道" | "大概"在部署领域等于"可能出事" |
| "先部署，有问题再回滚" | 回滚有成本，预防胜于治疗 |
| "依赖版本应该没变，直接构建下游" | API 接口变更后旧版本必然编译失败 |
| "这个 P2 用例不重要，先跳过" | P2 失败可能掩盖 P1 的连锁问题 |
| "截图太麻烦了" | 没截图的 E2E 测试等于没证据 |
| "这几个用例逻辑一样，测一个就行" | 每条用例可能触发不同的 bug |
| "页面看起来没问题，直接 PASS" | "看起来"不是证据，执行操作才是 |
| "用例太多了，跳过低优先级的" | 优先级低不代表不需要测试 |
| "`--profile` 可以隔离 Cookie" | `--profile` 不是有效选项，被静默忽略。必须用 `--config` + `isolated: true` |
| "`-s=agent1` 就是 `--session agent1`" | `-s` 不是 `--session` 的别名，回退到 default session，100% 污染 |
| "用 `close` 切换账号就行" | `close` 只关页面，Cookie 残留。必须用 `session-stop` |
