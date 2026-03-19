"""
质效平台（iPipeline）自动化构建与部署脚本

通过 playwright-cli 驱动浏览器完成：
1. SSO 登录
2. 触发构建（指定分支）
3. 轮询构建状态（每 30 秒刷新）
4. 自动发现页面上所有部署环境，依次触发部署
5. 逐个轮询每个环境的部署状态（每 30 秒刷新）

用法：
    python build_and_deploy.py \
        --url "http://console.devops.iflytek.com/ipipeline/applicationPipeline?projectId=xxx&appId=yyy" \
        --branch "release/your-branch" \
        --env dev,test              # 指定部署阶段（可选，默认部署所有阶段）
        --deploy-targets 0,1        # 指定部署按钮索引（可选，默认部署所有环境）
        --session deploy            # playwright-cli session name
        --deploy-only "2.0#1276"    # 跳过构建，直接部署指定版本（可选）

--env 参数说明：
    dev   → 开发环境
    test  → 测试环境
    pre   → 预上线环境
    支持逗号分隔多选，如 --env dev,test
    不指定时默认部署所有环境
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time

# ============================================================
# DOM 选择器常量（2026-03-05 审计验证）
# ============================================================

# --- 流水线操作按钮（通过 title 属性定位，稳定） ---
SEL_BUILD_EXEC_BTN   = 'button[title="构建执行"]'
SEL_DEPLOY_EXEC_BTN  = 'button[title="部署执行"]'

# --- 构建弹窗 ---
SEL_BRANCH_INPUT     = ".ivu-auto-complete input.ivu-input"
SEL_BRANCH_DROPDOWN  = ".ivu-select-dropdown.ivu-auto-complete .ivu-select-item"

# --- 部署弹窗 ---
SEL_VERSION_SELECT   = ".ivu-select .ivu-select-selection"
SEL_VERSION_DROPDOWN = ".ivu-select-dropdown .ivu-select-item"

# --- 状态监测 ---
STATE_SUCCESS  = "ipipeline-state-suc"
STATE_FAIL     = "ipipeline-state-fail"
STATE_DOING    = "ipipeline-doing"
STATE_WAITING  = "ipipeline-waiting"
STATE_ABORT    = "ipipeline-abort"

POLL_INTERVAL = 30
MAX_POLL_COUNT = 60

# --- 环境映射（--env 参数值 → 页面阶段标题栏文本） ---
# 页面结构：ul.clearfix[0] 是标题栏，ul.clearfix[1] 是内容区，两者 li 一一对应
# 通过标题栏文本精准匹配，不依赖 li 索引顺序
ENV_STAGE_TITLE = {"dev": "部署(开发阶段)", "test": "部署(测试阶段)", "pre": "部署(预上线阶段)"}
ENV_STAGE_LABEL = {"dev": "开发", "test": "测试", "pre": "预上线"}

# 定位 playwright-cli 可执行文件
PLAYWRIGHT_CLI = shutil.which("playwright-cli") or "playwright-cli"

# 跨平台：macOS 用 Meta 键（Cmd），Windows/Linux 用 Control 键
SELECT_ALL_MODIFIER = "Meta" if sys.platform == "darwin" else "Control"


def _to_oneliner(code):
    """将多行 JS 压缩为单行，自动补分号以弥补 ASI 失效。

    Windows 的 subprocess 通过 .CMD 批处理传参时无法正确传递换行符，
    必须压缩为单行。但 JS 的 ASI 依赖换行符推断分号，压缩后失效。
    因此在压缩前为每行末尾补显式分号（已有终结符的行除外）。
    """
    lines = code.strip().split('\n')
    processed = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s == '}':
            pass  # lone block closer — no semicolon
        elif not s.endswith((';', '{', ',', '(')):
            s += ';'
        processed.append(s)
    result = ' '.join(processed).rstrip(';')
    # Fix: }; before else/catch/finally breaks if-else/try-catch chains
    result = re.sub(r'};\s*(else|catch|finally)\b', r'} \1', result)
    return result


def run_cli(session, code, timeout=30):
    """执行 playwright-cli run-code 并返回输出。"""
    cmd = [PLAYWRIGHT_CLI, f"-s={session}", "run-code", _to_oneliner(code)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, encoding='utf-8', errors='replace')
        return (result.stdout or '') + (result.stderr or '')
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def run_cli_json(session, js_code, timeout=30):
    """执行 JS 代码并解析 JSON 返回值"""
    output = run_cli(session, js_code, timeout)
    match = re.search(r'### Result\n(.+?)(?:\n###|\Z)', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            return match.group(1).strip()
    return output


def run_simple(session, *args, timeout=15):
    """执行简单的 playwright-cli 命令（如 click, fill, snapshot）"""
    cmd = [PLAYWRIGHT_CLI, f"-s={session}"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, encoding='utf-8', errors='replace')
        return (result.stdout or '') + (result.stderr or '')
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def session_exists(session):
    """检查 playwright-cli session 是否已存在（浏览器已打开）。

    使用白名单策略：只在拿到预期结构的成功响应时才返回 True。
    任何异常（超时、未打开、语法错误等）一律视为不存在。
    """
    code = "async page => ({ url: page.url(), title: await page.title() })"
    result = run_cli_json(session, code, timeout=5)
    return isinstance(result, dict) and 'url' in result


def open_browser(session, url):
    """打开浏览器并导航到 URL（如果 session 已存在则跳过）"""
    if session_exists(session):
        print(f"  复用已有 session: {session}")
        return
    cmd = [PLAYWRIGHT_CLI, f"-s={session}", "open", url, "--headed"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)


def goto(session, url):
    """导航到 URL 并等待加载"""
    code = f'''async page => {{
  await page.goto('{url}', {{ waitUntil: 'load', timeout: 20000 }}).catch(function() {{}})
  await page.waitForTimeout(3000)
  var t = ''
  try {{ t = await page.title() }} catch(e) {{ t = 'nav_in_progress' }}
  return {{ url: page.url(), title: t }}
}}'''
    return run_cli_json(session, code, timeout=45)


def get_credentials():
    """从环境变量获取 SSO 凭据"""
    username = os.environ.get("IFLYTEK_SSO_USERNAME")
    password_b64 = os.environ.get("IFLYTEK_SSO_PASSWORD")
    if not username or not password_b64:
        print("ERROR: 缺少环境变量 IFLYTEK_SSO_USERNAME / IFLYTEK_SSO_PASSWORD（密码为 base64 编码）")
        sys.exit(1)
    password = base64.b64decode(password_b64).decode("utf-8")
    return username, password


def need_login(session):
    """检查当前页面是否需要登录"""
    code = "async page => ({ url: page.url(), title: await page.title() })"
    result = run_cli_json(session, code)
    if not isinstance(result, dict):
        return True
    url = result.get("url", "").lower()
    return "login" in url or "sso" in url


def sso_login(session):
    """SSO 登录 — 使用 role-based 选择器（2026-03 验证）

    流程：E3 登录页 → 点击"使用集团账号登录" → SSO 统一认证页 → 填写凭据 → 登录
    SSO 页面的 input 元素无 id 属性，必须使用 role-based 定位。
    """
    username, password = get_credentials()

    # Step 1: 点击 E3 "使用集团账号登录" 按钮（遍历所有 button 查找）
    code = f'''async page => {{
  await page.waitForSelector('button', {{ timeout: 10000 }}).catch(function() {{}})
  var btns = await page.$$('button')
  if (btns.length === 0) return {{ action: 'no_button' }}
  var target = null
  for (var i = 0; i < btns.length; i++) {{
    var text = await btns[i].textContent()
    if (text && text.indexOf('集团账号') !== -1) {{ target = btns[i]; break }}
  }}
  if (!target) return {{ action: 'no_e3_btn', total: btns.length, url: page.url() }}
  await target.click()
  await page.waitForTimeout(5000)
  return {{ action: 'e3_clicked', url: page.url(), title: await page.title() }}
}}'''
    step1 = run_cli_json(session, code, timeout=30)
    print(f"  E3 跳转: {step1}")

    # Step 2: 填写 SSO 凭据并登录
    # SSO 页面的 textbox 没有 id，通过 placeholder/name 属性定位
    code = f'''async page => {{
  await page.waitForTimeout(3000)
  await page.waitForSelector('button, input[type="submit"]', {{ timeout: 10000 }}).catch(function() {{}})
  var inputs = await page.$$('input[type="text"], input[type="password"], input:not([type])')
  if (inputs.length < 2) return {{ action: 'no_sso_inputs', count: inputs.length, url: page.url() }}
  var userInput = null
  var passInput = null
  for (var i = 0; i < inputs.length; i++) {{
    var type = await inputs[i].getAttribute('type')
    var placeholder = await inputs[i].getAttribute('placeholder') || ''
    if (type === 'password') {{ passInput = inputs[i] }}
    else if (placeholder.indexOf('账号') !== -1 || placeholder.indexOf('域') !== -1) {{ userInput = inputs[i] }}
  }}
  if (!userInput && inputs.length >= 2) {{ userInput = inputs[0] }}
  if (!passInput) {{
    for (var j = 0; j < inputs.length; j++) {{
      var t = await inputs[j].getAttribute('type')
      if (t === 'password') {{ passInput = inputs[j] }}
    }}
  }}
  if (!userInput || !passInput) return {{ action: 'inputs_not_found', url: page.url() }}
  await userInput.fill('{username}')
  await passInput.fill('{password}')
  await page.waitForTimeout(500)
  var loginBtns = await page.$$('button')
  var loginBtn = null
  for (var k = 0; k < loginBtns.length; k++) {{
    var btnText = await loginBtns[k].textContent()
    if (btnText && btnText.indexOf('登录') !== -1) {{ loginBtn = loginBtns[k]; break }}
  }}
  if (!loginBtn) {{
    var submitInputs = await page.$$('input[type="submit"]')
    if (submitInputs.length > 0) {{ loginBtn = submitInputs[0] }}
  }}
  if (!loginBtn) {{
    var allClickable = await page.$$('button, input[type="submit"], a.user-btn, .login-btn')
    return {{ action: 'no_login_btn', url: page.url(), clickableCount: allClickable.length }}
  }}
  await loginBtn.click()
  await page.waitForTimeout(8000)
  return {{ action: 'logged_in', url: page.url(), title: await page.title() }}
}}'''
    result = run_cli_json(session, code, timeout=45)
    print(f"  登录结果: {result}")
    return result


def dismiss_modals(session):
    """关闭干扰弹窗（如果存在）+ 清理遮罩层。

    防御性设计：
    - 弹窗可能存在也可能不存在（临时性提示，将来可能被平台移除）
    - 只在 ivu-modal-wrap 容器内搜索按钮，不影响页面其他元素
    - 通过弹窗内容关键词识别是否为干扰弹窗，而非仅匹配按钮文本
    - 清理遮罩时只处理已关闭的弹窗，不影响正在使用的对话框
    """
    code = '''async page => {
  await page.waitForTimeout(1000)
  var count = await page.evaluate(function() {
    var closed = 0
    var wraps = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    wraps.forEach(function(wrap) {
      if (wrap.classList.contains('ivu-modal-hidden')) return
      if (wrap.offsetParent === null && wrap.style.display === 'none') return
      var content = wrap.textContent || ''
      var isDismissable = false
      var dismissBtn = null
      if (content.indexOf('项目编码') !== -1 || content.indexOf('编码为空') !== -1) {
        dismissBtn = wrap.querySelector('button')
        if (dismissBtn) {
          var btns = Array.from(wrap.querySelectorAll('button'))
          dismissBtn = btns.find(function(b) { return b.textContent.trim() === '暂不修改' }) || btns[0]
        }
        isDismissable = true
      }
      if (content.indexOf('pomp') !== -1 || content.indexOf('已结项') !== -1) {
        var btns = Array.from(wrap.querySelectorAll('button'))
        dismissBtn = btns.find(function(b) { return b.textContent.trim() === '我知道了' }) || btns[0]
        isDismissable = true
      }
      if (isDismissable && dismissBtn) {
        try {
          dismissBtn.click()
          wrap.style.pointerEvents = 'none'
          var mask = wrap.querySelector('.ivu-modal-mask')
          if (mask) mask.style.display = 'none'
          closed++
        } catch(e) {}
      }
    })
    return closed
  })
  if (count > 0) {
    await page.waitForTimeout(1500)
  }
  return count
}'''
    result = run_cli_json(session, code)
    return result


def js_click(session, css_selector, nth=0):
    """通过 JS 原生 el.click() 点击元素，绕过 iView overlay 拦截。

    这是解决 ivu-modal-wrap 持久化问题的核心方法：
    Playwright 的 page.click() 会被 overlay 阻塞 timeout，
    但 JS 原生 el.click() 不受 pointer-events 限制。
    """
    code = f'''async page => {{
  var els = await page.$$('{css_selector}')
  if (els.length <= {nth}) return {{ clicked: false, error: 'element not found at index {nth}, total: ' + els.length }}
  await els[{nth}].evaluate(function(el) {{ el.click() }})
  return {{ clicked: true, index: {nth}, total: els.length }}
}}'''
    return run_cli_json(session, code)


def discover_deploy_targets(session, stage_titles=None):
    """动态发现页面上带部署按钮的环境。

    Args:
        stage_titles: 要部署的阶段标题列表（如 ["部署(开发阶段)", "部署(测试阶段)"]）。
                      通过与页面标题栏文本精准匹配来过滤。None 表示所有环境。
    """
    filter_json = json.dumps(stage_titles, ensure_ascii=False) if stage_titles else "null"
    code = (
        "async page => await page.evaluate(function(titleFilter) {"
        "  var uls = document.querySelectorAll('ul.clearfix');"
        "  var headerUl = uls[0];"
        "  var contentUl = uls[1];"
        "  if (!headerUl || !contentUl) return [];"
        "  var headerLis = Array.from(headerUl.children);"
        "  var contentLis = Array.from(contentUl.children);"
        "  var allowedIndices = null;"
        "  if (titleFilter) {"
        "    allowedIndices = [];"
        "    headerLis.forEach(function(li, idx) {"
        "      var title = li.textContent.trim();"
        "      if (titleFilter.indexOf(title) !== -1) allowedIndices.push(idx);"
        "    });"
        "  }"
        "  var allStageLefts = Array.from(document.querySelectorAll('.app-stage-left'));"
        "  var allDeployBtns = Array.from(document.querySelectorAll('button[title=\"部署执行\"]'));"
        "  var targets = [];"
        "  allDeployBtns.forEach(function(btn, btnIdx) {"
        "    var envContainer = btn.closest('.envContainer');"
        "    if (!envContainer) return;"
        "    var contentLi = envContainer.closest('ul.clearfix > li');"
        "    var liIdx = contentLi && contentLi.parentElement ? Array.from(contentLi.parentElement.children).indexOf(contentLi) : -1;"
        "    if (allowedIndices && allowedIndices.indexOf(liIdx) === -1) return;"
        "    var stageName = (liIdx >= 0 && liIdx < headerLis.length) ? headerLis[liIdx].textContent.trim() : '';"
        "    var stageLeft = envContainer.querySelector('.app-stage-left');"
        "    if (!stageLeft) return;"
        "    var globalIdx = allStageLefts.indexOf(stageLeft);"
        "    var text = stageLeft.textContent.trim().replace(/\\s+/g, ' ').substring(0, 200);"
        "    var nameEl = envContainer.querySelector('.ellipsis span') || envContainer.querySelector('.ellipsis');"
        "    var envName = nameEl ? nameEl.textContent.trim() : text.substring(0, 50);"
        "    var icon = stageLeft.querySelector('i[class*=\"ipipeline\"]');"
        "    var iconClass = icon ? icon.className : '';"
        "    var status = 'unknown';"
        "    if (iconClass.indexOf('state-suc') !== -1) status = 'success';"
        "    else if (iconClass.indexOf('state-fail') !== -1) status = 'fail';"
        "    else if (iconClass.indexOf('doing') !== -1) status = 'doing';"
        "    else if (iconClass.indexOf('waiting') !== -1) status = 'waiting';"
        "    targets.push({"
        "      btnIndex: btnIdx,"
        "      envName: envName,"
        "      stageName: stageName,"
        "      stageLeftGlobalIndex: globalIdx,"
        "      currentStatus: status,"
        "      currentText: text"
        "    });"
        "  });"
        "  return targets;"
        "}, " + filter_json + ")"
    )
    return run_cli_json(session, code)



def get_current_build_num(session):
    """获取当前最新构建的 buildNum，用于触发新构建后判断是否产生了新记录。"""
    code = '''async page => await page.evaluate(function() {
  var buildStage = document.querySelectorAll('.app-stage-left')[0]
  if (!buildStage) return null
  var buildNum = buildStage.querySelector('.build-num')
  if (!buildNum) return null
  var title = buildNum.title || buildNum.getAttribute('title') || buildNum.textContent.trim()
  var match = title.match(/[\d.]+#(\d+)/)
  return match ? match[1] : buildNum.textContent.trim()
})'''
    result = run_cli_json(session, code)
    return str(result) if result else None


def trigger_build(session, branch):
    """触发构建：点击构建执行 → 处理 pomp 弹窗 → 填写分支 → 执行"""

    # 1. 点击构建执行按钮
    # 先尝试 Playwright 原生 click（force=true 绕过 overlay），回退到 JS dispatchEvent
    click_code = f'''async page => {{
  var btn = await page.$('button[title="构建执行"]')
  if (!btn) return {{ clicked: false, error: 'button not found' }}
  try {{
    await btn.click({{ force: true, timeout: 3000 }})
    return {{ clicked: true, method: 'playwright_force' }}
  }} catch(e) {{
    var result = await btn.evaluate(function(el) {{
      var ev = new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }})
      el.dispatchEvent(ev)
      return 'dispatched'
    }})
    return {{ clicked: true, method: 'dispatchEvent' }}
  }}
}}'''
    result = run_cli_json(session, click_code)
    print(f"  构建按钮: {result}")
    time.sleep(3)

    # DEBUG: 检查点击后页面上所有可见 modal 的状态
    debug_code = f'''async page => await page.evaluate(function() {{
  var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
  return modals.map(function(m) {{
    var hidden = m.classList.contains('ivu-modal-hidden')
    var title = (m.querySelector('.ivu-modal-header') || {{}}).textContent || ''
    var hasInput = !!m.querySelector('.ivu-auto-complete input.ivu-input')
    var classes = m.className
    return {{ hidden: hidden, title: title.trim(), hasInput: hasInput, classes: classes }}
  }})
}})'''
    debug_result = run_cli_json(session, debug_code)
    print(f"  DEBUG 页面 modals: {debug_result}")

    # DEBUG: 检查页面上所有按钮
    debug_btn_code = f'''async page => await page.evaluate(function() {{
  var btns = Array.from(document.querySelectorAll('button[title]'))
  return btns.map(function(b) {{ return {{ title: b.getAttribute('title'), visible: b.offsetParent !== null, disabled: b.disabled }} }})
}})'''
    debug_btn_result = run_cli_json(session, debug_btn_code)
    print(f"  DEBUG 页面 buttons: {debug_btn_result}")

    # 2. 处理 pomp 过期弹窗（点击构建时可能触发，也可能不触发）
    #    注意：pomp 弹窗和构建对话框可能同时打开，
    #    关闭 pomp 后构建对话框仍在，不需要重新点击构建按钮。
    #    只有在构建对话框未打开时才需要重新点击。
    dismissed = dismiss_modals(session)
    if isinstance(dismissed, int) and dismissed > 0:
        print(f"  关闭了 {dismissed} 个弹窗")
        time.sleep(1)
        # 检查构建对话框是否已经打开（通过检查分支输入框是否存在）
        check_code = f'''async page => await page.evaluate(function(sel) {{
  var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
  var hasDialog = modals.some(function(m) {{
    return !m.classList.contains('ivu-modal-hidden') && m.querySelector(sel)
  }})
  return hasDialog ? 'dialog_open' : 'dialog_not_open'
}}, '{SEL_BRANCH_INPUT}')'''
        dialog_state = run_cli_json(session, check_code)
        if dialog_state != 'dialog_open':
            print(f"  构建对话框未打开，重新点击构建按钮")
            result = js_click(session, SEL_BUILD_EXEC_BTN)
            print(f"  重新点击: {result}")
            time.sleep(2)
        else:
            print(f"  构建对话框已打开，继续")

    # 3. 填写分支名
    code = f'''async page => {{
  var found = await page.evaluate(function(sel) {{
    var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    var visible = modals.filter(function(m) {{ return !m.classList.contains('ivu-modal-hidden') && m.querySelector(sel) }})
    if (visible.length === 0) return 'no build dialog'
    var input = visible[0].querySelector(sel)
    if (!input) return 'no branch input'
    input.click()
    input.focus()
    return 'focused'
  }}, '{SEL_BRANCH_INPUT}')
  if (found !== 'focused') return found
  await page.waitForTimeout(300)
  await page.keyboard.press('{SELECT_ALL_MODIFIER}+a')
  await page.keyboard.press('Backspace')
  await page.waitForTimeout(500)
  await page.keyboard.type('{branch}', {{ delay: 80 }})
  await page.waitForSelector('{SEL_BRANCH_DROPDOWN}', {{ timeout: 5000 }}).catch(function() {{}})
  await page.waitForTimeout(500)
  return 'branch typed'
}}'''
    result = run_cli_json(session, code, timeout=30)
    print(f"  分支输入: {result}")

    if result in ('no build dialog', 'no branch input'):
        return {"triggered": False, "detail": result}

    # 4. 从下拉中选择匹配的分支（精确 → 部分匹配 → 仅输入）
    code = f'''async page => {{
  var result = await page.evaluate(function(args) {{
    var items = Array.from(document.querySelectorAll(args.sel))
    var texts = items.map(function(i) {{ return i.textContent.trim() }})
    var target = items.find(function(li) {{ return li.textContent.trim() === args.branch }})
    if (target) {{ target.click(); return {{ selected: true, match: 'exact', branch: args.branch }} }}
    var partial = items.find(function(li) {{ return li.textContent.trim().indexOf(args.branch) !== -1 || args.branch.indexOf(li.textContent.trim()) !== -1 }})
    if (partial) {{ partial.click(); return {{ selected: true, match: 'partial', matched: partial.textContent.trim() }} }}
    return {{ selected: false, typed: args.branch, available: texts.slice(0, 5) }}
  }}, {{ branch: '{branch}', sel: '{SEL_BRANCH_DROPDOWN}' }})
  await page.waitForTimeout(500)
  return result
}}'''
    result = run_cli_json(session, code)
    if isinstance(result, dict) and result.get('selected'):
        print(f"  分支选择: {result.get('match')} — {result.get('branch') or result.get('matched')}")
    else:
        print(f"  分支选择: 下拉未匹配（将使用输入框文本），诊断: {result}")

    # 5. 点击执行按钮（使用 JS evaluate 绕过 overlay）
    code = '''async page => {
  var result = await page.evaluate(function() {
    var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    var visible = modals.filter(function(m) {
      return !m.classList.contains('ivu-modal-hidden') && m.querySelector('.ivu-modal-footer')
    })
    if (visible.length === 0) return 'no dialog'
    var footer = visible[visible.length - 1].querySelector('.ivu-modal-footer')
    if (!footer) return 'no footer'
    var execBtn = footer.querySelector('.ivu-btn-primary')
    if (!execBtn) {
      var buttons = Array.from(footer.querySelectorAll('button'))
      execBtn = buttons.find(function(b) { return b.textContent.trim() === '执行' })
    }
    if (execBtn) { execBtn.click(); return 'executed' }
    return 'exec button not found'
  })
  await page.waitForTimeout(3000)
  return result
}'''
    result = run_cli_json(session, code)
    print(f"  构建触发: {result}")

    if result in ('no dialog', 'exec button not found', 'no footer'):
        return {"triggered": False, "detail": result}
    return {"triggered": True, "detail": result}


def poll_build_status(session, pipeline_url, old_build_num=None):
    """轮询构建状态。

    Args:
        old_build_num: 触发构建前的最新 buildNum。如果提供，轮询时会跳过
                       buildNum 未变化的情况，避免误读旧构建的状态。
    """
    print(f"\n--- 开始轮询构建状态（每 {POLL_INTERVAL} 秒） ---")
    if old_build_num:
        print(f"  旧构建编号: {old_build_num}（将等待新编号出现）")

    for i in range(MAX_POLL_COUNT):
        goto(session, pipeline_url)
        dismiss_modals(session)

        code = '''async page => await page.evaluate(function() {
  var stageLefts = Array.from(document.querySelectorAll('.app-stage-left'))
  if (stageLefts.length === 0) return { status: 'unknown', error: 'no stage items' }
  var buildItem = stageLefts[0]
  var stateIcon = buildItem.querySelector('i[class*=ipipeline-state], i[class*=ipipeline-doing], i[class*=ipipeline-waiting], i[class*=ipipeline-abort]')
  var buildNum = buildItem.querySelector('.build-num')
  var iconClass = stateIcon ? stateIcon.className : ''
  var status = 'unknown'
  if (iconClass.indexOf('state-suc') !== -1) status = 'success'
  else if (iconClass.indexOf('state-fail') !== -1) status = 'fail'
  else if (iconClass.indexOf('doing') !== -1) status = 'doing'
  else if (iconClass.indexOf('waiting') !== -1) status = 'waiting'
  else if (iconClass.indexOf('abort') !== -1) status = 'abort'
  var numText = buildNum ? buildNum.textContent.trim() : null
  var numTitle = buildNum ? (buildNum.title || buildNum.getAttribute('title')) : null
  var numMatch = (numTitle || '').match(/[\d.]+#(\d+)/)
  var extractedNum = numMatch ? numMatch[1] : numText
  return { status: status, iconClass: iconClass, buildNum: extractedNum, version: numTitle }
})'''
        result = run_cli_json(session, code)
        print(f"  [{i+1}/{MAX_POLL_COUNT}] 构建状态: {result}")

        if isinstance(result, dict):
            current_num = result.get("buildNum")
            # 如果提供了旧编号且当前编号未变化，说明新构建记录尚未生成
            if old_build_num and current_num and str(current_num) == str(old_build_num):
                print(f"  构建记录尚未更新（仍是 #{old_build_num}），继续等待...")
                if i < MAX_POLL_COUNT - 1:
                    time.sleep(POLL_INTERVAL)
                continue

            status = result.get("status", "unknown")
            if status == "success":
                version = result.get("version", "")
                match = re.search(r'[\d.]+#\d+', version or "")
                build_version = match.group(0) if match else current_num
                print(f"\n  构建成功！版本: {build_version}")
                return {"status": "success", "version": build_version}
            elif status in ("fail", "abort"):
                print(f"\n  构建失败！状态: {status}")
                return {"status": "fail", "detail": result}

        if i < MAX_POLL_COUNT - 1:
            print(f"  等待 {POLL_INTERVAL} 秒...")
            time.sleep(POLL_INTERVAL)

    print("\n  构建超时")
    return {"status": "timeout"}


def trigger_deploy(session, deploy_stage_index, build_version):
    """触发部署：使用 JS 原生 click 绕过 overlay"""

    # 1. 点击部署执行按钮（JS 原生 click）
    result = js_click(session, SEL_DEPLOY_EXEC_BTN, deploy_stage_index)
    print(f"  部署按钮点击: {result}")

    if isinstance(result, dict) and not result.get("clicked"):
        return {"triggered": False, "detail": result.get("error")}

    time.sleep(2)  # 等待部署弹窗渲染

    # 2. 检查弹窗是否打开，并确认版本
    code = f'''async page => {{
  var result = await page.evaluate(function(targetVer) {{
    var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    var visible = modals.filter(function(m) {{
      return !m.classList.contains('ivu-modal-hidden') && m.querySelector('.ivu-modal-footer')
    }})
    if (visible.length === 0) return {{ step: 'no deploy dialog' }}
    var dialog = visible[visible.length - 1]
    var selectItems = dialog.querySelectorAll('.ivu-select-selected-value')
    var currentVer = ''
    if (selectItems.length > 0) {{
      currentVer = selectItems[0].textContent.trim()
    }} else {{
      var selectDiv = dialog.querySelector('.ivu-select-selection div')
      if (selectDiv) currentVer = selectDiv.textContent.trim()
    }}
    return {{ step: 'dialog_open', currentVersion: currentVer, targetVersion: targetVer }}
  }}, '{build_version}')
  return result
}}'''
    dialog_info = run_cli_json(session, code)
    print(f"  弹窗状态: {dialog_info}")

    if isinstance(dialog_info, dict) and dialog_info.get("step") == "no deploy dialog":
        return {"triggered": False, "detail": "deploy dialog not opened"}

    # 3. 如果当前版本不是目标版本，打开下拉选择
    current_ver = dialog_info.get("currentVersion", "") if isinstance(dialog_info, dict) else ""
    if current_ver and build_version not in current_ver and current_ver not in build_version:
        print(f"  当前版本 {current_ver} 不是目标版本 {build_version}，切换...")
        # 点击下拉触发
        code = f'''async page => {{
  var result = await page.evaluate(function(sel) {{
    var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    var visible = modals.filter(function(m) {{ return !m.classList.contains('ivu-modal-hidden') && m.querySelector('.ivu-modal-footer') }})
    if (visible.length === 0) return 'no dialog'
    var trigger = visible[visible.length - 1].querySelector(sel)
    if (trigger) {{ trigger.click(); return 'dropdown opened' }}
    return 'no version trigger'
  }}, '{SEL_VERSION_SELECT}')
  await page.waitForTimeout(1500)
  return result
}}'''
        run_cli(session, code)

        # 选择目标版本
        code = f'''async page => {{
  var result = await page.evaluate(function(ver) {{
    var items = Array.from(document.querySelectorAll('{SEL_VERSION_DROPDOWN}'))
    var target = items.find(function(li) {{ var t = li.textContent.trim(); return t === ver || t.indexOf(ver) !== -1 || ver.indexOf(t) !== -1 }})
    if (target) {{ target.click(); return 'version selected: ' + target.textContent.trim() }}
    return 'version ' + ver + ' not found, first 5: ' + items.slice(0, 5).map(function(i) {{ return i.textContent.trim() }}).join(', ')
  }}, '{build_version}')
  await page.waitForTimeout(500)
  return result
}}'''
        result = run_cli_json(session, code)
        print(f"  版本选择: {result}")

    # 4. 点击执行按钮（JS evaluate 绕过 overlay）
    code = '''async page => {
  var result = await page.evaluate(function() {
    var modals = Array.from(document.querySelectorAll('.ivu-modal-wrap'))
    var visible = modals.filter(function(m) {
      return !m.classList.contains('ivu-modal-hidden') && m.querySelector('.ivu-modal-footer')
    })
    if (visible.length === 0) return 'no dialog'
    var footer = visible[visible.length - 1].querySelector('.ivu-modal-footer')
    if (!footer) return 'no footer'
    var execBtn = footer.querySelector('.ivu-btn-primary')
    if (!execBtn) {
      var buttons = Array.from(footer.querySelectorAll('button'))
      execBtn = buttons.find(function(b) { return b.textContent.trim() === '执行' })
    }
    if (execBtn) { execBtn.click(); return 'executed' }
    return 'exec button not found, buttons: ' + Array.from(footer.querySelectorAll('button')).map(function(b) { return b.textContent.trim() }).join(', ')
  })
  await page.waitForTimeout(3000)
  return result
}'''
    result = run_cli_json(session, code)
    print(f"  部署触发: {result}")

    if result in ('no dialog', 'exec button not found', 'no footer') or \
       (isinstance(result, str) and 'not found' in result):
        return {"triggered": False, "detail": result}
    return {"triggered": True, "detail": result}


def poll_single_deploy_status(session, pipeline_url, stage_left_global_index, env_name, build_version):
    """轮询单个环境的部署状态"""
    build_num = build_version.split("#")[-1] if "#" in build_version else build_version

    print(f"\n--- 轮询部署状态: {env_name}（stage-left[{stage_left_global_index}]） ---")

    for i in range(MAX_POLL_COUNT):
        goto(session, pipeline_url)
        dismiss_modals(session)

        code = f'''async page => await page.evaluate(function(args) {{
  var stageLefts = Array.from(document.querySelectorAll('.app-stage-left'))
  var el = stageLefts[args.idx]
  if (!el) return {{ status: 'unknown', error: 'stage-left index ' + args.idx + ' not found' }}
  var text = el.textContent.trim().replace(/\\s+/g, ' ')
  var stateIcon = el.querySelector('i[class*="ipipeline-state"], i[class*="ipipeline-doing"], i[class*="ipipeline-waiting"], i[class*="ipipeline-abort"]')
  var iconClass = stateIcon ? stateIcon.className : ''
  var status = 'unknown'
  if (iconClass.indexOf('state-suc') !== -1) status = 'success'
  else if (iconClass.indexOf('state-fail') !== -1) status = 'fail'
  else if (iconClass.indexOf('doing') !== -1) status = 'doing'
  else if (iconClass.indexOf('waiting') !== -1) status = 'waiting'
  else if (iconClass.indexOf('abort') !== -1) status = 'abort'
  var hasBuildNum = text.indexOf(args.buildNum) !== -1
  return {{ status: status, iconClass: iconClass, text: text.substring(0, 150), matchesBuild: hasBuildNum }}
}}, {{ idx: {stage_left_global_index}, buildNum: '{build_num}' }})'''
        result = run_cli_json(session, code)
        print(f"  [{i+1}/{MAX_POLL_COUNT}] {env_name}: {result}")

        if isinstance(result, dict):
            status = result.get("status", "unknown")
            matches = result.get("matchesBuild", False)
            if matches:
                if status == "success":
                    print(f"\n  {env_name} 部署成功！")
                    return {"status": "success", "envName": env_name}
                elif status in ("fail", "abort"):
                    print(f"\n  {env_name} 部署失败！")
                    return {"status": "fail", "envName": env_name, "detail": result}
            elif status in ("doing", "waiting"):
                pass  # 继续等待

        if i < MAX_POLL_COUNT - 1:
            print(f"  等待 {POLL_INTERVAL} 秒...")
            time.sleep(POLL_INTERVAL)

    print(f"\n  {env_name} 部署超时")
    return {"status": "timeout", "envName": env_name}


def check_single_deploy_already_done(session, stage_left_global_index, build_version):
    """检查单个环境是否已部署指定版本"""
    build_num = build_version.split("#")[-1] if "#" in build_version else build_version
    code = f'''async page => await page.evaluate(function(args) {{
  var stageLefts = Array.from(document.querySelectorAll('.app-stage-left'))
  var el = stageLefts[args.idx]
  if (!el) return {{ alreadyDeployed: false, error: 'not found' }}
  var text = el.textContent.trim().replace(/\\s+/g, ' ')
  var icon = el.querySelector('i[class*="ipipeline-state-suc"]')
  if (text.indexOf(args.buildNum) !== -1 && icon) {{
    return {{ alreadyDeployed: true, text: text.substring(0, 150) }}
  }}
  return {{ alreadyDeployed: false, text: text.substring(0, 150) }}
}}, {{ idx: {stage_left_global_index}, buildNum: '{build_num}' }})'''
    return run_cli_json(session, code)


def main():
    sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
    sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')

    parser = argparse.ArgumentParser(description="质效平台自动化构建与部署")
    parser.add_argument("--url", required=True, help="质效平台应用流水线 URL")
    parser.add_argument("--branch", required=True, help="构建分支名")
    parser.add_argument("--env", default="",
                        help="部署环境（逗号分隔）：dev=开发, test=测试, pre=预上线。留空部署所有环境")
    parser.add_argument("--deploy-targets", default="",
                        help="部署按钮索引（逗号分隔），留空则自动部署所有环境")
    parser.add_argument("--session", default="deploy", help="playwright-cli session 名称")
    parser.add_argument("--deploy-only", default="", help="跳过构建，直接部署指定版本")
    args = parser.parse_args()

    session = args.session
    pipeline_url = args.url

    deploy_target_indices = None
    if args.deploy_targets:
        deploy_target_indices = [int(x.strip()) for x in args.deploy_targets.split(",")]

    # 解析 --env 参数，转换为阶段标题列表（用于页面文本匹配）
    stage_titles = None
    env_labels = []
    if args.env:
        envs = [e.strip().lower() for e in args.env.split(",") if e.strip()]
        invalid = [e for e in envs if e not in ENV_STAGE_TITLE]
        if invalid:
            print(f"ERROR: 无效的 --env 值: {invalid}，可选值: dev, test, pre")
            sys.exit(1)
        stage_titles = [ENV_STAGE_TITLE[e] for e in envs]
        env_labels = [f"{e}({ENV_STAGE_LABEL[e]})" for e in envs]

    print("=" * 60)
    print("质效平台自动化构建与部署")
    print(f"  URL:    {pipeline_url}")
    print(f"  分支:   {args.branch}")
    if env_labels:
        print(f"  部署环境: {', '.join(env_labels)}")
    else:
        print(f"  部署环境: 所有环境")
    if deploy_target_indices:
        print(f"  部署按钮索引: {deploy_target_indices}")
    print("=" * 60)

    # Step 1: 打开浏览器
    print("\n[1/7] 打开浏览器...")
    open_browser(session, pipeline_url)
    page_info = goto(session, pipeline_url)
    print(f"  页面加载完成: {page_info}")

    # Step 2: SSO 登录
    print("\n[2/7] 检查登录状态...")
    if need_login(session):
        print("  需要登录，执行 SSO 登录...")
        login_result = sso_login(session)
        already_on_target = isinstance(login_result, dict) and 'ipipeline' in login_result.get('url', '')
        if not already_on_target:
            goto(session, pipeline_url)
        if need_login(session):
            print("  SSO 登录失败")
            subprocess.run([PLAYWRIGHT_CLI, f"-s={session}", "close"], capture_output=True)
            sys.exit(1)
        print("  登录成功")
    else:
        print("  已有登录态")

    # Step 3: 关闭干扰弹窗
    print("\n[3/7] 处理弹窗...")
    closed = dismiss_modals(session)
    print(f"  关闭了 {closed} 个弹窗" if isinstance(closed, int) and closed > 0 else "  无弹窗")

    # deploy-only 模式
    if args.deploy_only:
        build_version = args.deploy_only
        build_result = {"status": "skipped", "version": build_version}
        print(f"\n--deploy-only 模式，跳过构建，直接部署版本: {build_version}")
    else:
        # Step 4: 触发构建
        print(f"\n[4/7] 触发构建...")
        # 记录触发前的最新构建编号，用于轮询时判断新构建是否已生成
        old_build_num = get_current_build_num(session)
        print(f"  当前最新构建编号: {old_build_num}")

        print(f"  触发构建（分支: {args.branch}）...")
        build_trigger = trigger_build(session, args.branch)

        if not build_trigger.get("triggered"):
            print(f"\n  构建未触发: {build_trigger.get('detail')}")
            subprocess.run([PLAYWRIGHT_CLI, f"-s={session}", "close"], capture_output=True)
            sys.exit(1)

        # Step 5: 轮询构建
        print("\n[5/7] 等待构建完成...")
        build_result = poll_build_status(session, pipeline_url, old_build_num=old_build_num)

        if build_result["status"] != "success":
            print(f"\n构建失败: {build_result['status']}")
            print(json.dumps(build_result, indent=2, ensure_ascii=False))
            subprocess.run([PLAYWRIGHT_CLI, f"-s={session}", "close"], capture_output=True)
            sys.exit(1)

        build_version = build_result["version"]
        print(f"\n构建版本: {build_version}")

    # Step 6: 发现部署目标
    print(f"\n[6/7] 发现部署目标（版本: {build_version}）...")
    goto(session, pipeline_url)
    dismiss_modals(session)

    targets = discover_deploy_targets(session, stage_titles=stage_titles)
    if not isinstance(targets, list) or len(targets) == 0:
        print("  无部署目标")
        final_result = {"build": build_result, "deploy": {"status": "no_targets"}}
        print("\n" + "=" * 60)
        print("最终结果:")
        print(json.dumps(final_result, indent=2, ensure_ascii=False))
        sys.exit(0)

    if deploy_target_indices is not None:
        targets = [t for t in targets if t["btnIndex"] in deploy_target_indices]
        if not targets:
            print(f"  指定索引 {deploy_target_indices} 无匹配")
            subprocess.run([PLAYWRIGHT_CLI, f"-s={session}", "close"], capture_output=True)
            sys.exit(1)

    # 构建 stageName → 显示标签的映射
    title_to_label = {v: ENV_STAGE_LABEL[k] for k, v in ENV_STAGE_TITLE.items()}
    print(f"  发现 {len(targets)} 个部署目标:")
    for t in targets:
        stage_label = title_to_label.get(t.get('stageName', ''), '')
        stage_tag = f" [{stage_label}]" if stage_label else ""
        print(f"    [{t['btnIndex']}] {t['envName']}{stage_tag} (当前: {t['currentStatus']})")

    # Step 7: 并行部署 — 先统一触发所有环境，再逐一轮询状态
    deploy_results = []
    triggered_targets = []  # 需要轮询的目标

    # Phase 1: 逐个触发部署（不刷新页面，避免 DOM 重建导致按钮索引失效）
    print("\n--- Phase 1: 触发所有部署 ---")
    for ti, target in enumerate(targets):
        env_name = target["envName"]
        btn_index = target["btnIndex"]
        sl_index = target["stageLeftGlobalIndex"]
        print(f"\n[7.{ti+1}/{len(targets)}] 触发部署: {env_name}")

        dismiss_modals(session)

        # 触发部署
        deploy_trigger = trigger_deploy(session, btn_index, build_version)

        if not deploy_trigger.get("triggered"):
            print(f"  部署未触发: {deploy_trigger.get('detail')}")
            deploy_results.append({"envName": env_name, "btnIndex": btn_index, "status": "not_triggered", "detail": deploy_trigger.get("detail")})
            continue

        triggered_targets.append(target)

    # Phase 2: 逐一轮询已触发环境的部署状态
    if triggered_targets:
        print(f"\n--- Phase 2: 轮询 {len(triggered_targets)} 个环境的部署状态 ---")
        for target in triggered_targets:
            env_name = target["envName"]
            btn_index = target["btnIndex"]
            sl_index = target["stageLeftGlobalIndex"]
            result = poll_single_deploy_status(session, pipeline_url, sl_index, env_name, build_version)
            result["btnIndex"] = btn_index
            deploy_results.append(result)

    # 不关闭浏览器 — 保留 session 供后续项目复用登录态
    # 调用方可通过 playwright-cli -s={session} close 手动关闭

    # 输出结果
    final_result = {"build": build_result, "deploy": deploy_results}
    print("\n" + "=" * 60)
    print("最终结果:")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))

    print("\n--- 部署汇总 ---")
    all_ok = True
    for dr in deploy_results:
        ok = dr["status"] in ("success", "reused")
        if not ok:
            all_ok = False
        print(f"  [{'OK' if ok else 'FAIL'}] {dr.get('envName', '?')}: {dr['status']}")

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
