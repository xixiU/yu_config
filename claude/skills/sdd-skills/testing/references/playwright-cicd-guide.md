# 质效平台 Playwright 自动化操作指南

> **项目适配文档**：以下内容为特定质效平台的操作参考。如果你的团队使用不同的 CI/CD 平台，请替换此文件中的 URL、DOM 选择器和登录流程。

通过 `playwright-cli` 驱动浏览器操作质效平台，完成构建与部署。

---

## 快速使用

### 自动化脚本（推荐）

```bash
python {SKILL_DIR}/scripts/build_and_deploy.py \
  --url "{质效地址}" \
  --branch "{分支名}" \
  --env "dev,test" \
  --session deploy
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--url` | 质效平台应用流水线 URL（含 projectId 和 appId） | 必填 |
| `--branch` | 构建分支名 | 必填 |
| `--env` | 部署环境（逗号分隔多选）：`dev`=开发, `test`=测试, `pre`=预上线。留空部署所有环境 | 所有环境 |
| `--deploy-targets` | 部署按钮索引（逗号分隔），如 `0,1`。留空则自动部署所有环境 | 所有 |
| `--session` | playwright-cli session 名称 | deploy |
| `--deploy-only` | 跳过构建，直接部署指定版本 | 可选 |

### 环境变量

| 变量 | 说明 |
|------|------|
| `IFLYTEK_SSO_USERNAME` | SSO 用户名 |
| `IFLYTEK_SSO_PASSWORD` | SSO 密码（base64 编码） |

---

## 脚本流程概览

脚本自动完成以下全流程：

1. **打开浏览器** — 导航到质效平台
2. **SSO 登录** — 从环境变量获取凭据自动登录
3. **关闭干扰弹窗** — 自动处理项目编码失效、pomp 过期等提示
4. **触发构建** — 输入目标分支名，从下拉中选中后点击执行
5. **轮询构建状态** — 每 30 秒刷新页面，检查状态图标直到成功或失败
6. **触发部署** — 自动选择构建成功的版本号，对每个环境执行部署
7. **轮询部署状态** — 每 30 秒刷新页面，检查状态直到成功或失败

---

## 页面结构与 DOM 选择器

### SSO 登录页（2026-03 验证）

**登录流程分两步：E3 登录页 → SSO 统一认证页**

| 步骤 | 元素 | 选择器（Playwright role-based） | 备注 |
|------|------|-------------------------------|------|
| 1. E3 登录页 | "使用集团账号登录" 按钮 | `page.getByRole('button', { name: '使用集团账号登录' })` | 点击后跳转到 sso.iflytek.com |
| 2. SSO 用户名 | 域账号输入框 | `page.getByRole('textbox', { name: /输入域账号/ })` | 无 id 属性，只能用 role+name |
| 3. SSO 密码 | 密码输入框 | `page.getByRole('textbox', { name: '输入密码' })` | 无 id 属性 |
| 4. SSO 登录 | 登录按钮 | `page.getByRole('button', { name: '登录' })` | 提交后跳转回质效平台 |

> **历史变更记录：** 2026 年前 SSO 使用 `input#username` / `input#password` / `input.user-btn[type=submit]`，现已改为无 id 的 textbox + button。

### iPipeline 主页

流水线阶段从左到右：构建 → 部署(开发阶段) → 部署(测试阶段) → 部署(预上线阶段) → 部署(生产阶段)

每个阶段记录卡片右侧的操作按钮通过 `title` 属性区分：

| 操作 | CSS 选择器 | icon class |
|------|-----------|-----------|
| 构建执行 | `button[title="构建执行"]` | `ipipeline-do` |
| 构建日志详情 | `button[title="构建日志详情"]` | `ipipeline-details` |
| 构建操作历史 | `button[title="构建操作历史"]` | `ipipeline-log` |
| 下载构建包 | `button[title="下载构建包"]` | `ipipeline-download` |
| 部署执行 | `button[title="部署执行"]` | `ipipeline-do` |
| 部署日志详情 | `button[title="部署日志详情"]` | `ipipeline-details` |

> 多个"部署执行"按钮按页面顺序对应各环境，通过 `querySelectorAll` 索引定位。

### 干扰弹窗（关键！）

**弹窗触发时机不同，需分别处理：**

| 弹窗 | 触发时机 | 关闭按钮 | Playwright 选择器 |
|------|---------|---------|------------------|
| 项目编码失效 | 页面首次加载 | "暂不修改" | `page.getByRole('button', { name: '暂不修改' })` |
| pomp 过期提示 | 点击"构建执行"时 | "我知道了" | `page.getByRole('button', { name: '我知道了' })` |

**⚠️ 致命问题：iView Modal 遮罩层持久化**

iView UI 框架的 `div.ivu-modal-wrap` 在弹窗关闭后**永远不会从 DOM 中移除**，会持续拦截所有 pointer events。

**表现：** 关闭弹窗后，后续所有 `page.click()` 调用均 timeout 失败：
```
<div class="ivu-modal-wrap">…</div> subtree intercepts pointer events
```

**解决方案：** 所有点击操作必须使用 JS 原生 `el.click()` 而非 Playwright 的 `click()`：

```javascript
// ❌ 错误 — 会被 ivu-modal-wrap 阻塞
await page.click('button[title="构建执行"]');

// ✅ 正确 — 绕过 Playwright actionability 检查
await page.$eval('button[title="构建执行"]', el => el.click());

// ✅ 正确 — 通过 ref 绑定的 evaluate
await page.getByRole('button', { name: '暂不修改' }).evaluate(el => el.click());
```

**附加清理：** 关闭弹窗后，隐藏所有遮罩层（可选但推荐）：
```javascript
await page.evaluate(function() {
  document.querySelectorAll('.ivu-modal-mask').forEach(function(el) {
    el.style.display = 'none';
  });
});
```

### 构建弹窗

点击"构建执行"后弹出：

| 元素 | CSS 选择器 | 说明 |
|------|-----------|------|
| 分支名输入 | `.ivu-auto-complete input.ivu-input` | 自动补全组件，textbox |
| 分支下拉选项 | `.ivu-select-dropdown.ivu-auto-complete .ivu-select-item` | 点击选中 |
| 取消按钮 | footer 内 `button` 文本="取消" | |
| **执行按钮** | footer 内 `button` 文本="执行" | 或 `.ivu-btn-primary` |

分支输入交互：清空 → 键入分支名 → 等待下拉出现 → 点击精确匹配项

### 部署弹窗

点击"部署执行"后弹出：

| 元素 | CSS 选择器 | 说明 |
|------|-----------|------|
| 部署类型 | 只读文本 | 如 SHELL |
| 部署环境 | 只读文本 | 如 精准上云 |
| 制品版本下拉触发 | `.ivu-select .ivu-select-selection` | 点击打开 |
| 版本下拉选项 | `.ivu-select-dropdown .ivu-select-item` | 文本如 `3.0#1278` |
| 取消按钮 | footer 内 `button` 文本="取消" | |
| **执行按钮** | footer 内 `button` 文本="执行" | 或 `.ivu-btn-primary` |

> 部署弹窗默认已选中最新构建版本。如果目标版本就是最新版，无需操作下拉。

---

## 状态监测

构建和部署的状态通过记录卡片上的图标 class 判断：

| 状态 | icon class | 含义 |
|------|-----------|------|
| 成功 | `ipipeline-state-suc` | 完成 |
| 失败 | `ipipeline-state-fail` | 失败 |
| 执行中 | `ipipeline-doing` | 继续等待 |
| 等待中 | `ipipeline-waiting` | 继续等待 |
| 中止 | `ipipeline-abort` | 已中止 |

### 轮询策略

1. 触发构建/部署后，每 **30 秒**刷新页面
2. 读取最新记录的状态图标 class
3. `doing` / `waiting` → 继续轮询
4. `state-suc` → 成功，进入下一步
5. `state-fail` / `abort` → 失败，停止并报告

### 版本号获取

构建成功后，从最新构建记录中提取版本号：

```
选择器: .app-stage-left:first-child .build-num
属性:   title="版本号：3.0#1278"
```

提取 `3.0#1278` 用于后续部署时选择制品版本。

---

## 交互序列总结（固化流程）

完整的自动化交互序列（每一步都经过 2026-03-05 实测验证）：

```
1. open(url) → 跳转到 E3 登录页或直接进入 iPipeline

2. IF 登录页:
   click("使用集团账号登录")  → 跳转到 sso.iflytek.com
   fill(域账号输入框, username)
   fill(密码输入框, password)
   click("登录")             → 跳转回 iPipeline

3. 关闭弹窗:
   IF 存在 "暂不修改" → el.click()  // 项目编码失效
   wait(1s)
   清理遮罩层

4. 触发构建:
   el.click('[title=构建执行]')
   IF 弹出 "我知道了" → el.click()  // pomp过期
   wait(1s), 清理遮罩层
   el.click('[title=构建执行]')      // 重新点击
   wait(2s)                          // 等构建弹窗渲染
   fill(分支输入框, branch)
   wait(2s)                          // 等下拉选项加载
   click(匹配的分支选项)
   el.click("执行" 按钮)

5. 轮询构建:
   LOOP every 30s, max 30min:
     reload page
     读取构建状态图标 class
     IF success → 提取版本号, BREAK
     IF fail/abort → 报错, EXIT

6. 触发部署 (对每个目标环境):
   el.click('[title=部署执行]'[index])
   wait(2s)                          // 等部署弹窗渲染
   IF 需要选版本 → 点下拉, 选目标版本
   el.click("执行" 按钮)

7. 轮询部署:
   LOOP every 30s, max 10min:
     reload page
     读取部署状态图标 class
     IF success → BREAK
     IF fail/abort → 报错
```
