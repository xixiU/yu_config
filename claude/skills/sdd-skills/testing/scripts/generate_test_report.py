#!/usr/bin/env python3
"""
Generate a standardized HTML test report from test-results.json.

Usage:
    python generate_test_report.py \
        --results test-results.json \
        --screenshots screenshots/ \
        --output test-report.html \
        --module "学科学情" \
        --env "test.zhixue.com" \
        --scope "高中 / 高一 / 笔盒1班" \
        --subject "数学" \
        --tester "xinzhou26" \
        --note "可选备注"

Results JSON schema:
{
  "results": [
    {
      "id": "TC-XKXQ-0001",
      "module": "学情总览",
      "name": "学科学情入口",
      "status": "PASS | FAIL | SKIP",
      "screenshot": "screenshots/xxx.png",  // optional, relative path
      "error": "error message or null",
      "notes": "observation notes"
    }
  ]
}
"""

import argparse
import json
import os
import base64
from datetime import datetime
from collections import defaultdict, OrderedDict
from html import escape


def load_image_base64(path, screenshots_dir):
    candidates = [path, os.path.join(screenshots_dir, path),
                  os.path.join(screenshots_dir, os.path.basename(path))]
    for p in candidates:
        if p and os.path.isfile(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return None


def extract_bugs(results):
    """Group FAIL results into logical bugs."""
    fails = [r for r in results if r["status"] == "FAIL"]
    if not fails:
        return []

    # Group by similar error messages (first 40 chars as key)
    groups = OrderedDict()
    for r in fails:
        err = (r.get("error") or "").strip()
        key = err[:40] if err else r["id"]
        if key not in groups:
            groups[key] = {"ids": [], "error": err}
        groups[key]["ids"].append(r["id"])

    bugs = []
    for i, (_, g) in enumerate(groups.items(), 1):
        severity = "HIGH" if len(g["ids"]) >= 3 else ("HIGH" if any(k in g["error"] for k in ["缺少", "缺失", "无法", "不存在"]) else "MEDIUM")
        bugs.append({
            "bug_id": f"BUG-{i:03d}",
            "cases": ", ".join(g["ids"]),
            "severity": severity,
            "description": g["error"]
        })
    return bugs


def severity_badge(sev):
    colors = {"HIGH": ("#fff1f0", "#ff4d4f"), "MEDIUM": ("#fff7e6", "#fa8c16"), "LOW": ("#f5f5f5", "#8c8c8c")}
    bg, fg = colors.get(sev, colors["MEDIUM"])
    return f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:3px;font-size:12px;font-weight:600;">{sev}</span>'


def status_badge(status):
    cls = {"PASS": "badge-pass", "FAIL": "badge-fail", "SKIP": "badge-skip"}
    return f'<span class="badge {cls.get(status, "badge-skip")}">{status}</span>'


def generate_report(results_path, screenshots_dir, output_path, module_name, env_url, scope, subject, tester, note):
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    results = data.get("results", [])

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    executed = passed + failed
    pass_rate = f"{(passed / executed * 100):.1f}" if executed > 0 else "0.0"
    pct_pass = f"{(passed / total * 100):.1f}" if total else "0"
    pct_fail = f"{(failed / total * 100):.1f}" if total else "0"
    pct_skip = f"{(skipped / total * 100):.1f}" if total else "0"

    by_module = OrderedDict()
    for r in results:
        mod = r.get("module", "未分类")
        if mod not in by_module:
            by_module[mod] = []
        by_module[mod].append(r)

    bugs = extract_bugs(results)
    now = datetime.now().strftime("%Y-%m-%d")

    # --- Build bugs table ---
    bugs_rows = ""
    for b in bugs:
        bugs_rows += (
            f'<tr><td style="font-weight:600;">{b["bug_id"]}</td>'
            f'<td>{escape(b["cases"])}</td>'
            f'<td>{severity_badge(b["severity"])}</td>'
            f'<td>{escape(b["description"])}</td></tr>'
        )

    bugs_section = ""
    if bugs:
        bugs_section = f'''
<div class="bugs-section"><div class="collapsible-header open" onclick="toggleBugs(this)">
<span class="arrow">&#9654;</span><h2>已知缺陷（{len(bugs)} 个）</h2></div>
<div id="bugs-content"><table class="bug-table"><thead><tr>
<th style="width:90px;">缺陷ID</th><th style="width:200px;">关联用例</th>
<th style="width:90px;">严重程度</th><th>缺陷描述</th>
</tr></thead><tbody>{bugs_rows}</tbody></table></div></div>'''

    # --- Build module sections ---
    modules_html = ""
    sc_counter = 0
    for mod, cases in by_module.items():
        m_pass = sum(1 for c in cases if c["status"] == "PASS")
        m_fail = sum(1 for c in cases if c["status"] == "FAIL")
        m_skip = sum(1 for c in cases if c["status"] == "SKIP")

        rows = ""
        for r in cases:
            row_cls = ' class="row-fail"' if r["status"] == "FAIL" else ""

            # Notes/error cell
            cell_parts = []
            if r["status"] == "FAIL" and r.get("error"):
                cell_parts.append(f'<span style="color:#ff4d4f;">{escape(r["error"])}</span>')
            elif r["status"] == "SKIP" and r.get("error"):
                cell_parts.append(f'<span style="color:#8c8c8c;">跳过原因：{escape(r["error"])}</span>')
            elif r.get("notes"):
                cell_parts.append(escape(r["notes"]))

            # Screenshot toggle
            sc_html = ""
            if r.get("screenshot"):
                img_b64 = load_image_base64(r["screenshot"], screenshots_dir)
                if img_b64:
                    sc_id = r["id"].replace("-", "_")
                    sc_html = (
                        f'<div class="screenshot-toggle" onclick="toggleScreenshot(\'{sc_id}\')">'
                        f'&#128247; 查看截图</div>'
                        f'<div id="sc_{sc_id}" class="screenshot-container" style="display:none;">'
                        f'<img class="screenshot-img" src="data:image/png;base64,{img_b64}"></div>'
                    )

            notes_content = "<br>".join(cell_parts) + sc_html
            rows += (
                f'<tr{row_cls}>'
                f'<td class="td-id">{r["id"]}</td>'
                f'<td class="td-name">{escape(r["name"])}</td>'
                f'<td class="td-status">{status_badge(r["status"])}</td>'
                f'<td class="td-notes">{notes_content}</td>'
                f'</tr>'
            )

        modules_html += f'''
<div class="module-section"><div class="module-header"><h3>{escape(mod)}</h3><div class="module-stats">
<span class="stat-pill pass-pill">{m_pass} 通过</span>
<span class="stat-pill fail-pill">{m_fail} 失败</span>
<span class="stat-pill skip-pill">{m_skip} 跳过</span>
<span class="stat-pill total-pill">共 {len(cases)} 条</span>
</div></div><table class="result-table"><thead><tr>
<th style="width:130px;">ID</th><th style="width:240px;">用例名称</th>
<th style="width:80px;">状态</th><th>备注</th>
</tr></thead><tbody>{rows}</tbody></table></div>'''

    # --- Note line ---
    note_html = f'<div class="header-note">{escape(note)}</div>' if note else ""

    # --- Full HTML ---
    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(module_name)}模块 - 测试报告</title>
<style>* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#333; line-height:1.6; padding:20px; }}
.container {{ max-width:1200px; margin:0 auto; background:#fff; border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden; }}
.report-header {{ background:linear-gradient(135deg,#1a73e8 0%,#0d47a1 100%); color:#fff; padding:32px 40px; }}
.report-header h1 {{ font-size:28px; font-weight:700; margin-bottom:8px; }}
.report-header .subtitle {{ font-size:14px; opacity:0.85; margin-bottom:16px; }}
.env-info {{ display:flex; flex-wrap:wrap; gap:8px 24px; font-size:13px; opacity:0.9; }}
.env-info span {{ background:rgba(255,255,255,0.15); padding:3px 10px; border-radius:4px; }}
.header-note {{ margin-top:12px; font-size:12px; opacity:0.75; font-style:italic; }}
.summary-section {{ padding:24px 40px; border-bottom:1px solid #f0f0f0; }}
.summary-section h2 {{ font-size:18px; margin-bottom:16px; color:#1a1a1a; }}
.summary-cards {{ display:flex; gap:16px; margin-bottom:20px; flex-wrap:wrap; }}
.summary-card {{ flex:1; min-width:140px; padding:20px; border-radius:8px; text-align:center; }}
.summary-card .card-value {{ font-size:36px; font-weight:700; line-height:1.2; }}
.summary-card .card-label {{ font-size:14px; margin-top:4px; opacity:0.85; }}
.card-total {{ background:#e6f7ff; color:#1890ff; }}
.card-pass {{ background:#f6ffed; color:#52c41a; }}
.card-fail {{ background:#fff1f0; color:#ff4d4f; }}
.card-skip {{ background:#fafafa; color:#8c8c8c; }}
.card-rate {{ background:#fff7e6; color:#fa8c16; }}
.progress-bar {{ height:24px; border-radius:12px; overflow:hidden; display:flex; background:#f5f5f5; margin-top:8px; }}
.progress-pass {{ background:#52c41a; height:100%; display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:600; }}
.progress-fail {{ background:#ff4d4f; height:100%; display:flex; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:600; }}
.progress-skip {{ background:#d9d9d9; height:100%; display:flex; align-items:center; justify-content:center; color:#595959; font-size:11px; font-weight:600; }}
.progress-legend {{ display:flex; gap:20px; margin-top:8px; font-size:12px; color:#666; }}
.legend-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; vertical-align:middle; }}
.bugs-section {{ padding:24px 40px; border-bottom:1px solid #f0f0f0; }}
.bugs-section h2 {{ font-size:18px; margin-bottom:4px; color:#1a1a1a; }}
.collapsible-header {{ cursor:pointer; display:flex; align-items:center; gap:8px; user-select:none; padding:8px 0; }}
.collapsible-header .arrow {{ transition:transform 0.2s; font-size:12px; }}
.collapsible-header.open .arrow {{ transform:rotate(90deg); }}
.bug-table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:13px; }}
.bug-table th {{ background:#fafafa; padding:10px 12px; text-align:left; font-weight:600; border-bottom:2px solid #f0f0f0; color:#555; }}
.bug-table td {{ padding:10px 12px; border-bottom:1px solid #f0f0f0; }}
.modules-section {{ padding:24px 40px 40px; }}
.modules-section > h2 {{ font-size:18px; margin-bottom:20px; color:#1a1a1a; }}
.module-section {{ margin-bottom:28px; border:1px solid #e8e8e8; border-radius:8px; overflow:hidden; }}
.module-header {{ background:#fafafa; padding:14px 20px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; border-bottom:1px solid #e8e8e8; }}
.module-header h3 {{ font-size:16px; color:#1a1a1a; }}
.module-stats {{ display:flex; gap:8px; flex-wrap:wrap; }}
.stat-pill {{ font-size:12px; padding:2px 10px; border-radius:10px; font-weight:600; }}
.pass-pill {{ background:#f6ffed; color:#52c41a; }}
.fail-pill {{ background:#fff1f0; color:#ff4d4f; }}
.skip-pill {{ background:#f5f5f5; color:#8c8c8c; }}
.total-pill {{ background:#e6f7ff; color:#1890ff; }}
.result-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.result-table thead th {{ background:#fafafa; padding:10px 14px; text-align:left; font-weight:600; border-bottom:2px solid #f0f0f0; color:#555; position:sticky; top:0; }}
.result-table tbody td {{ padding:10px 14px; border-bottom:1px solid #f5f5f5; vertical-align:top; }}
.result-table tbody tr:hover {{ background:#fafafa; }}
.row-fail {{ background:#fff8f8 !important; }}
.row-fail:hover {{ background:#fff1f0 !important; }}
.td-id {{ font-family:"SFMono-Regular",Consolas,monospace; font-size:12px; color:#555; white-space:nowrap; }}
.td-name {{ font-weight:500; }}
.td-status {{ text-align:center; }}
.td-notes {{ color:#666; font-size:12px; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:3px; font-size:12px; font-weight:600; letter-spacing:0.5px; }}
.badge-pass {{ background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }}
.badge-fail {{ background:#fff1f0; color:#ff4d4f; border:1px solid #ffa39e; }}
.badge-skip {{ background:#f5f5f5; color:#8c8c8c; border:1px solid #d9d9d9; }}
.screenshot-toggle {{ cursor:pointer; color:#1890ff; font-size:12px; margin-top:6px; user-select:none; }}
.screenshot-toggle:hover {{ text-decoration:underline; }}
.screenshot-container {{ margin-top:8px; }}
.screenshot-img {{ max-width:100%; max-height:400px; border:1px solid #e8e8e8; border-radius:4px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
.report-footer {{ text-align:center; padding:16px 40px; font-size:12px; color:#999; border-top:1px solid #f0f0f0; }}
@media print {{ body {{ background:#fff; padding:0; }} .container {{ box-shadow:none; }} .report-header {{ background:#1a73e8 !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }} .summary-card,.badge,.stat-pill,.progress-pass,.progress-fail,.progress-skip,.row-fail {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }} .screenshot-container {{ display:block !important; page-break-inside:avoid; }} .screenshot-toggle {{ display:none; }} }}
</style></head><body><div class="container">
<div class="report-header"><h1>{escape(module_name)}模块 - 测试报告</h1>
<div class="subtitle">{escape(env_url)} &middot; SIT环境测试</div>
<div class="env-info">
<span>日期: {now}</span><span>环境: {escape(env_url)}</span>
<span>范围: {escape(scope)}</span>
<span>学科: {escape(subject)}</span><span>浏览器: Chrome / Playwright MCP</span>
<span>测试员: {escape(tester)}</span></div>
{note_html}
</div>
<div class="summary-section"><h2>测试概况</h2><div class="summary-cards">
<div class="summary-card card-total"><div class="card-value">{total}</div><div class="card-label">总用例数</div></div>
<div class="summary-card card-pass"><div class="card-value">{passed}</div><div class="card-label">通过</div></div>
<div class="summary-card card-fail"><div class="card-value">{failed}</div><div class="card-label">失败</div></div>
<div class="summary-card card-skip"><div class="card-value">{skipped}</div><div class="card-label">跳过</div></div>
<div class="summary-card card-rate"><div class="card-value">{pass_rate}%</div><div class="card-label">通过率 (PASS/已测)</div></div>
</div>
<div class="progress-bar">
<div class="progress-pass" style="width:{pct_pass}%;">{passed}</div>
<div class="progress-fail" style="width:{pct_fail}%;">{failed}</div>
<div class="progress-skip" style="width:{pct_skip}%;">{skipped}</div>
</div><div class="progress-legend">
<span><span class="legend-dot" style="background:#52c41a;"></span>通过 {passed} ({pct_pass}%)</span>
<span><span class="legend-dot" style="background:#ff4d4f;"></span>失败 {failed} ({pct_fail}%)</span>
<span><span class="legend-dot" style="background:#d9d9d9;"></span>跳过 {skipped} ({pct_skip}%)</span>
</div></div>
{bugs_section}
<div class="modules-section"><h2>各模块测试结果</h2>{modules_html}</div>
<div class="report-footer">报告生成时间: {now} &nbsp;|&nbsp; {escape(module_name)}模块测试报告 &nbsp;|&nbsp; 自动生成</div>
</div><script>function toggleScreenshot(id) {{
    var el = document.getElementById('sc_' + id);
    if (el.style.display === 'none') {{ el.style.display = 'block'; }}
    else {{ el.style.display = 'none'; }}
}}
function toggleBugs(header) {{
    var content = document.getElementById('bugs-content');
    if (content.style.display === 'none') {{ content.style.display = 'block'; header.classList.add('open'); }}
    else {{ content.style.display = 'none'; header.classList.remove('open'); }}
}}</script></body></html>'''

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {output_path}")
    print(f"Summary: {total} total, {passed} passed, {failed} failed, {skipped} skipped ({pass_rate}% pass rate)")
    if bugs:
        print(f"Bugs: {len(bugs)} defects extracted from {failed} failures")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate HTML test report")
    p.add_argument("--results", required=True, help="Path to test-results.json")
    p.add_argument("--screenshots", default="screenshots", help="Directory containing screenshots")
    p.add_argument("--output", required=True, help="Output HTML file path")
    p.add_argument("--module", default="测试", help="Module name (e.g. 学科学情)")
    p.add_argument("--env", default="", help="Test environment URL")
    p.add_argument("--scope", default="", help="Test scope (e.g. 高中 / 高一 / 笔盒1班)")
    p.add_argument("--subject", default="", help="Subject (e.g. 数学)")
    p.add_argument("--tester", default="", help="Tester name")
    p.add_argument("--note", default="", help="Optional header note")
    args = p.parse_args()
    generate_report(args.results, args.screenshots, args.output,
                    args.module, args.env, args.scope, args.subject, args.tester, args.note)
