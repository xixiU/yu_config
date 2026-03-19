# Playwright MCP 常用模式

浏览器自动化中使用 Playwright MCP 工具的常见操作序列参考。

---

## 1. 页面导航与验证

```bash
# 导航并验证页面已加载
playwright-cli -s=agentN goto {URL}
playwright-cli -s=agentN snapshot                    # 验证页面内容，获取元素引用
playwright-cli -s=agentN run-code "async page => await page.waitForSelector('预期元素选择器')"
```

---

## 2. 登录流程

```bash
playwright-cli -s=agentN goto {LOGIN_URL}
playwright-cli -s=agentN snapshot
playwright-cli -s=agentN fill {ref} "username"
playwright-cli -s=agentN fill {ref} "password"
playwright-cli -s=agentN click {ref}                 # 点击登录按钮
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(2000)"
playwright-cli -s=agentN snapshot                    # 验证登录成功
```

---

## 3. 下拉框 / 选择器交互

```bash
playwright-cli -s=agentN snapshot                    # 获取选择器元素引用
playwright-cli -s=agentN select {ref} "option-value"
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(1000)"  # 等待数据刷新
playwright-cli -s=agentN snapshot                    # 验证更新后状态
```

---

## 4. Tab / 二级导航

```bash
playwright-cli -s=agentN snapshot                    # 查找 Tab 元素引用
playwright-cli -s=agentN click {ref}                 # 点击 Tab
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(1000)"
playwright-cli -s=agentN snapshot                    # 验证 Tab 内容
```

---

## 5. 分页

```bash
playwright-cli -s=agentN snapshot                    # 查找分页按钮引用
playwright-cli -s=agentN click {ref}                 # 点击下一页
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(1000)"
playwright-cli -s=agentN snapshot                    # 验证下一页数据
```

---

## 6. 弹窗 / 对话框打开与关闭

```bash
playwright-cli -s=agentN click {ref}                 # 打开弹窗
playwright-cli -s=agentN run-code "async page => await page.waitForSelector('.el-dialog')"
playwright-cli -s=agentN snapshot                    # 验证弹窗内容

# 关闭弹窗
playwright-cli -s=agentN click {ref}                 # 点击关闭/取消按钮
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(500)"
```

---

## 7. 等待异步数据加载

```bash
# 策略A：等待特定元素出现
playwright-cli -s=agentN run-code "async page => await page.waitForSelector('.data-loaded')"

# 策略B：等待特定文字出现
playwright-cli -s=agentN run-code "async page => await page.waitForFunction(() => document.body.innerText.includes('预期文字'))"

# 策略C：固定等待（无可靠指示器时）
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(2000)"
```

---

## 8. 捕获截图

```bash
# 全视口截图
playwright-cli -s=agentN screenshot --filename=.ai-workspace/testing/screenshots/{TC-ID}.png

# 特定元素截图
playwright-cli -s=agentN screenshot --selector=".target-element" --filename=.ai-workspace/testing/screenshots/{TC-ID}-detail.png
```

---

## 9. 表单输入与提交

```bash
playwright-cli -s=agentN snapshot                    # 获取输入框引用
playwright-cli -s=agentN fill {ref} "测试值"
playwright-cli -s=agentN click {ref}                 # 点击提交按钮
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(1000)"
playwright-cli -s=agentN snapshot                    # 验证提交结果
```

---

## 10. 空状态验证

```bash
# 使用不会返回数据的参数导航
playwright-cli -s=agentN goto "{URL}?filter=no-data-condition"
playwright-cli -s=agentN run-code "async page => await page.waitForTimeout(1500)"
playwright-cli -s=agentN snapshot
# 验证空状态占位文字或图片是否可见
playwright-cli -s=agentN screenshot --filename=.ai-workspace/testing/screenshots/{TC-ID}-empty.png
```

---

## 11. 批量 DOM 状态验证（无需 snapshot）

替代多次 `snapshot` + 解析，直接用 JS 一次提取所有需要验证的状态：

```bash
playwright-cli -s=agentN run-code "async page => await page.evaluate(() => {
  const t = sel => document.querySelector(sel)?.textContent.trim() ?? null;
  const bg = sel => {
    const el = document.querySelector(sel);
    return el ? window.getComputedStyle(el).backgroundColor : null;
  };
  return {
    weakCount:    t('.stat-count.weak'),
    weakColor:    bg('.stat-circle.weak'),
    improveColor: bg('.stat-circle.to-improve'),
    statsText:    t('.overview-stats'),
  };
})"
```

---

## 12. 批量弹窗输入验证

打开弹窗一次，在单个脚本内顺序测试多种输入，关闭弹窗。减少 90%+ 工具调用：

```bash
playwright-cli -s=agentN run-code "async page => {
  // 1. 打开弹窗
  await page.evaluate(() => {
    const btns = document.querySelectorAll('button');
    for (const b of btns) { if (b.textContent.includes('目标按钮')) { b.click(); return; } }
  });
  await page.waitForTimeout(600);

  // 2. 辅助函数：填入值并读取实际值
  const typeAndRead = async (value) => {
    await page.evaluate(() => {
      const inp = document.querySelector('.el-dialog input:not([disabled])');
      inp.focus(); inp.select();
    });
    await page.keyboard.press('Control+a');
    await page.keyboard.type(value);
    await page.waitForTimeout(200);
    return page.evaluate(() =>
      document.querySelector('.el-dialog input:not([disabled])').value
    );
  };

  const r = {};
  r['TC-xxx-0001'] = { input: '150', actual: await typeAndRead('150') };
  r['TC-xxx-0002'] = { input: '65.5', actual: await typeAndRead('65.5') };
  r['TC-xxx-0003'] = { input: '@#!', actual: await typeAndRead('@#!') };

  // 3. 关闭弹窗
  await page.keyboard.press('Escape');
  return r;
}"
```

---

## 13. Cascader 级联选择器导航（JS 点击）

Element Plus Cascader 节点有时因 visibility 检查失败，改用 JS 点击：

```bash
playwright-cli -s=agentN run-code "async page => {
  const cascaders = await page.$$('.el-cascader');
  await cascaders[0].click();
  await page.waitForTimeout(400);

  const clickLevel = async (text) => {
    await page.evaluate(t => {
      const nodes = document.querySelectorAll('.el-cascader-node__label');
      for (const n of nodes) { if (n.textContent.trim() === t) { n.click(); return; } }
    }, text);
    await page.waitForTimeout(350);
  };

  await clickLevel('一级选项');
  await clickLevel('二级选项');
  await clickLevel('三级选项');
  await page.waitForTimeout(1500);
}"
```

---

## 14. 强制清理叠加弹窗遮罩

多次打开/关闭弹窗后，overlay 可能叠加导致点击被阻挡：

```bash
playwright-cli -s=agentN run-code "async page => {
  await page.evaluate(() => {
    document.querySelectorAll('.el-overlay-dialog').forEach(el => el.remove());
    document.querySelectorAll('.el-overlay').forEach(el => el.remove());
  });
  await page.waitForTimeout(200);
}"
```

---

## 15. 快速检查当前页面状态（无需 snapshot）

用于恢复测试前快速确认环境：

```bash
playwright-cli -s=agentN run-code "async page => await page.evaluate(() => ({
  url: location.href,
  title: document.title,
  bodyText: document.body.innerText.substring(0, 200)
}))"
```

---

## 16. Cookie 管理

playwright-cli 没有原生的 cookie-set / cookie-clear 命令，必须通过 `run-code` 操作 Playwright 的 Context API。

```bash
# 清除所有 Cookie
playwright-cli -s=agentN run-code "async page => {
  await page.context().clearCookies();
  return 'All cookies cleared';
}"

# 注入 Cookie（替代不存在的 cookie-set 命令）
playwright-cli -s=agentN run-code "async page => {
  await page.context().addCookies([
    { name: 'sessionId', value: 'abc123', domain: '.your-domain.com', path: '/' },
    { name: 'userId', value: '12345', domain: '.your-domain.com', path: '/' }
  ]);
  return 'Cookies injected';
}"

# 查看当前 Cookie
playwright-cli -s=agentN run-code "async page => {
  const cookies = await page.context().cookies('https://test.your-domain.com');
  return cookies.map(c => c.name + '=' + c.value);
}"

# 保存完整认证状态（Cookie + LocalStorage）到文件
playwright-cli -s=agentN run-code "async page => {
  const state = await page.context().storageState();
  require('fs').writeFileSync('auth-state.json', JSON.stringify(state, null, 2));
  return 'Saved ' + state.cookies.length + ' cookies';
}"

# 从文件加载认证状态
playwright-cli -s=agentN run-code "async page => {
  const state = JSON.parse(require('fs').readFileSync('auth-state.json', 'utf8'));
  await page.context().clearCookies();
  if (state.cookies?.length) await page.context().addCookies(state.cookies);
  return 'Loaded ' + state.cookies.length + ' cookies';
}"
```

---

## 常见问题与解决方案

| 问题 | 解决方案 |
|------|----------|
| 元素引用失效 | 导航或 DOM 更新后重新执行 `snapshot` |
| 点击无效果 | 在 snapshot 中确认元素可见/可用；尝试先等待元素出现 |
| 筛选切换后数据未刷新 | 在断言前使用 `waitForTimeout` 等待刷新 |
| 弹窗无法关闭 | 检查遮罩层 — 可能需要点击外部或查找关闭按钮 |
| 截图是空白的 | 截图前添加 `waitForTimeout(1000)` 等待渲染完成 |
| snapshot 输出超限 | 改用 `run-code` + `page.evaluate()` 直接查询 DOM |
| Cascader 节点 click 超时 | 改用 `page.evaluate()` 触发 JS click（见模式 13）|
| 多层弹窗遮罩叠加 | 执行模式 14（强制清理 `.el-overlay`）后再操作 |
| Cookie/Session 过期 | 用 `run-code` 重新 `page.context().addCookies([...])` 注入（见模式 16）|
| 多 Agent Cookie 交叉污染 | 使用 `isolated: true` 配置 + `session-stop` 切换账号（见 SKILL.md 浏览器启动章节）|
