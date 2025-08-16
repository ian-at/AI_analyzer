from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from ..utils.io import write_text


def _html_template(embed_json: str, title: str) -> str:
    # 改为占位符替换，避免 Python f-string 与 JS 模板字符串冲突
    html = """
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>[[TITLE]]</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, Segoe UI, Roboto, PingFang SC, Helvetica, Arial, sans-serif;
      margin: 0; padding: 20px; background: #f8f9fa; line-height: 1.6;
    }
    .container { max-width: 1200px; margin: 0 auto; }
    .header { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    .title { font-size: 24px; font-weight: 600; margin: 0 0 12px; color: #1f2937; }
    .meta-info { color: #6b7280; font-size: 14px; }

    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .stat-card {
      background: #fff; border-radius: 12px; padding: 20px; text-align: center;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.2s;
    }
    .stat-card:hover { transform: translateY(-2px); }
    .stat-number { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
    .stat-label { color: #6b7280; font-size: 14px; }
    .stat-high { color: #dc2626; }
    .stat-medium { color: #ea580c; }
    .stat-low { color: #16a34a; }
    .stat-total { color: #3b82f6; }

    .section { background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    .section-title { font-size: 18px; font-weight: 600; margin: 0 0 16px; color: #1f2937; }

    .filter-bar { display: flex; gap: 12px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }
    .filter-bar label { font-weight: 500; color: #374151; }
    input, select {
      padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 8px;
      font-size: 14px; transition: border-color 0.2s;
    }
    input:focus, select:focus { outline: none; border-color: #3b82f6; }

    .table-container { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
    th { background: #f9fafb; font-weight: 600; color: #374151; }
    tbody tr:hover { background: #f9fafb; }
    .reason-cell { max-width: 300px; word-wrap: break-word; white-space: normal; }

    .severity-badge {
      padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 500;
      display: inline-block; min-width: 60px; text-align: center;
    }
    .sev-high { background: #fef2f2; color: #dc2626; }
    .sev-medium { background: #fff7ed; color: #ea580c; }
    .sev-low { background: #f0fdf4; color: #16a34a; }

    .status-badge {
      padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 500;
      display: inline-block;
    }
    .status-normal { background: #f0fdf4; color: #16a34a; }
    .status-anomaly { background: #fef2f2; color: #dc2626; }

    .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; }
    .detail-card {
      background: #fff; border-radius: 12px; padding: 20px;
      border-left: 4px solid #e5e7eb; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .detail-card.high { border-left-color: #dc2626; }
    .detail-card.medium { border-left-color: #ea580c; }
    .detail-card.low { border-left-color: #16a34a; }

    .detail-header { margin-bottom: 16px; }
    .detail-title { font-weight: 600; color: #1f2937; font-size: 16px; margin-bottom: 8px; }
    .metric-label { color: #3b82f6; font-weight: 500; }
    .detail-meta { color: #6b7280; font-size: 14px; margin-bottom: 12px; }

    .reason-box {
      background: #f8fafc; border-radius: 8px; padding: 12px; margin-bottom: 16px;
      border-left: 3px solid #3b82f6;
    }
    .reason-title { font-weight: 500; color: #1e40af; margin-bottom: 4px; }

    .causes-section { margin-bottom: 16px; }
    .causes-title { font-weight: 500; color: #374151; margin-bottom: 8px; font-size: 14px; }
    .cause-item {
      background: #fef3f2; border-radius: 6px; padding: 10px; margin-bottom: 8px;
      border-left: 3px solid #f87171;
    }
    .cause-text { margin-bottom: 4px; }
    .cause-likelihood { font-size: 12px; color: #6b7280; }

    .suggestions-section { }
    .suggestions-title { font-weight: 500; color: #374151; margin-bottom: 8px; font-size: 14px; }
    .suggestion-item {
      background: #f0f9ff; border-radius: 6px; padding: 10px; margin-bottom: 8px;
      border-left: 3px solid #60a5fa;
    }

    .evidence-section { margin-bottom: 16px; }
    .evidence-title { font-weight: 500; color: #374151; margin-bottom: 8px; font-size: 14px; }
    .evidence-list { font-size: 13px; color: #6b7280; background: #f9fafb; padding: 10px; border-radius: 6px; }

    .footer {
      text-align: center; color: #9ca3af; font-size: 12px;
      margin-top: 40px; padding: 20px 0; border-top: 1px solid #e5e7eb;
    }

    @media (max-width: 768px) {
      .stats-grid { grid-template-columns: repeat(2, 1fr); }
      .detail-grid { grid-template-columns: 1fr; }
      .filter-bar { flex-direction: column; align-items: stretch; }
    }
  </style>
</head>
<body>
  <div class=\"container\">
    <!-- 头部信息 -->
    <div class=\"header\">
      <h1 class=\"title\">UB 异常分析报告</h1>
      <div id=\"meta\" class=\"meta-info\"></div>
    </div>

    <!-- 统计概览 -->
    <div class=\"stats-grid\" id=\"stats\"></div>

    <!-- 筛选和列表 -->
    <div class=\"section\">
      <h2 class=\"section-title\">异常检测结果</h2>
      <div class=\"filter-bar\">
        <label>筛选条件:</label>
        <input id=\"q\" placeholder=\"搜索 suite/case/metric...\" />
        <select id=\"sev\">
          <option value=\"\">所有严重级</option>
          <option value=\"high\">高危</option>
          <option value=\"medium\">中危</option>
          <option value=\"low\">低危</option>
        </select>
      </div>
      <div class=\"table-container\">
        <table id=\"anom-table\">
          <thead><tr>
            <th>测试套件</th><th>测试用例</th><th>指标</th><th>当前值</th><th>状态</th>
            <th>严重级别</th><th>置信度</th><th>主要原因</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <!-- 详细分析 -->
    <div class=\"section\">
      <h2 class=\"section-title\">详细分析报告</h2>
      <div class=\"detail-grid\" id=\"details\"></div>
    </div>

    <div class=\"footer\">
      报告生成时间: [[TS]]
    </div>
  </div>

  <script id=\"report-data\" type=\"application/json\">[[EMBED_JSON]]</script>
  <script>
    const data = JSON.parse(document.getElementById('report-data').textContent);
    const metaEl = document.getElementById('meta');
    metaEl.textContent = `运行ID: ${data.meta.run_id} | 日期: ${data.meta.date} | 补丁: ${data.meta.patch_id}/${data.meta.patch_set}`;

    function sevClass(s) { return s ? `sev-${s}` : ''; }
    function fmtPct(x) {
      if (x === null || x === undefined) return '';
      const n = typeof x === 'string' ? parseFloat(x) : x;
      if (!isFinite(n)) return '';
      return (n*100).toFixed(1) + '%';
    }
    function fmtConf(c) {
      if (c === null || c === undefined) return '';
      const n = typeof c === 'string' ? parseFloat(c) : c;
      if (!isFinite(n)) return '';
      const pct = n > 1 ? n : n * 100;
      return Math.round(pct) + '%';
    }
    function fmtVal(v) {
      if (v === null || v === undefined) return '';
      const n = (typeof v === 'string') ? (v.trim() === 'undefined' ? '' : v) : v;
      if (typeof n === 'number' && !isFinite(n)) return '';
      return n;
    }

    // 渲染统计概览
    const statsEl = document.getElementById('stats');
    const summary = data.summary || { total_anomalies: (data.anomalies||[]).length, severity_counts: {} };
    const counts = summary.severity_counts || {};

    statsEl.innerHTML = `
      <div class=\"stat-card\">
        <div class=\"stat-number stat-total\">${summary.total_anomalies}</div>
        <div class=\"stat-label\">总异常数</div>
      </div>
      <div class=\"stat-card\">
        <div class=\"stat-number stat-high\">${counts.high || 0}</div>
        <div class=\"stat-label\">高危异常</div>
      </div>
      <div class=\"stat-card\">
        <div class=\"stat-number stat-medium\">${counts.medium || 0}</div>
        <div class=\"stat-label\">中危异常</div>
      </div>
      <div class=\"stat-card\">
        <div class=\"stat-number stat-low\">${counts.low || 0}</div>
        <div class=\"stat-label\">低危异常</div>
      </div>
    `;

    const tbody = document.querySelector('#anom-table tbody');
    const detailsEl = document.getElementById('details');
    const allAnomalies = data.anomalies || [];

    function getSeverityBadge(severity) {
      if (!severity) return '<span class=\"status-badge status-normal\">正常</span>';
      const classMap = { high: 'sev-high', medium: 'sev-medium', low: 'sev-low' };
      const labelMap = { high: '高危', medium: '中危', low: '低危' };
      return `<span class=\"severity-badge ${classMap[severity] || ''}\">${labelMap[severity] || severity}</span>`;
    }

    function renderTable(list) {
      tbody.innerHTML = '';

      // 检查哪些列有数据
      const hasSuite = list.some(a => a.suite && a.suite.trim());
      const hasCase = list.some(a => a.case && a.case.trim());
      const hasCurrentValue = list.some(a => a.current_value !== null && a.current_value !== undefined);

      // 动态更新表头
      const headerRow = tbody.parentElement.querySelector('thead tr');
      let headers = [];
      if (hasSuite) headers.push('测试套件');
      if (hasCase) headers.push('测试用例');
      headers.push('指标');
      if (hasCurrentValue) headers.push('当前值');
      headers.push('状态', '严重级别', '置信度', '主要原因');

      headerRow.innerHTML = headers.map(h => `<th>${h}</th>`).join('');

      for(const a of list) {
        const tr = tbody.insertRow();
        const statusBadge = a.severity ?
          '<span class=\"status-badge status-anomaly\">异常</span>' :
          '<span class=\"status-badge status-normal\">正常</span>';

        let cells = [];
        if (hasSuite) cells.push(`<td>${a.suite || '-'}</td>`);
        if (hasCase) cells.push(`<td>${a.case || '-'}</td>`);
        cells.push(`<td>${a.metric || '-'}</td>`);
        if (hasCurrentValue) cells.push(`<td>${fmtVal(a.current_value)}</td>`);
        cells.push(`<td>${statusBadge}</td>`);
        cells.push(`<td>${getSeverityBadge(a.severity)}</td>`);
        cells.push(`<td>${fmtConf(a.confidence)}</td>`);
        cells.push(`<td class=\"reason-cell\">${a.primary_reason || '-'}</td>`);

        tr.innerHTML = cells.join('');
      }
    }

    function renderDetails(list) {
      detailsEl.innerHTML = '';
      const anomalousItems = list.filter(a => a.severity);

      if (anomalousItems.length === 0) {
        detailsEl.innerHTML = '<div style=\"text-align: center; color: #6b7280; padding: 40px;\">🎉 未检测到异常项，系统运行正常</div>';
        return;
      }

      for(const a of anomalousItems) {
        const card = document.createElement('div');
        card.className = `detail-card ${a.severity || ''}`;

        const rootCauses = (a.root_causes || []).map(r =>
          `<div class=\"cause-item\">
            <div class=\"cause-text\">${r.cause || ''}</div>
            <div class=\"cause-likelihood\">可能性: ${fmtConf(r.likelihood)}</div>
          </div>`
        ).join('');

        const suggestions = (a.suggested_next_checks || []).map(s =>
          `<div class=\"suggestion-item\">${s}</div>`
        ).join('');

        const evidence = (a.supporting_evidence || []).join('; ');

        // 构建更友好的标题
        let titleParts = [];
        if (a.suite && a.suite.trim()) titleParts.push(`套件: ${a.suite}`);
        if (a.case && a.case.trim()) titleParts.push(`用例: ${a.case}`);
        const title = titleParts.length > 0 ? titleParts.join(' | ') : '';

        card.innerHTML = `
          <div class=\"detail-header\">
            ${title ? `<div style=\"color: #6b7280; font-size: 13px; margin-bottom: 4px;\">${title}</div>` : ''}
            <div class=\"detail-title\">
              <span class=\"metric-label\">指标:</span> ${a.metric || '未知指标'}
            </div>
          </div>
          <div class=\"detail-meta\">
            ${getSeverityBadge(a.severity)} | 置信度: ${fmtConf(a.confidence)}${a.current_value !== null && a.current_value !== undefined ? ` | 当前值: ${fmtVal(a.current_value)}` : ''}
          </div>

          ${a.primary_reason ? `
          <div class=\"reason-box\">
            <div class=\"reason-title\">主要原因</div>
            <div>${a.primary_reason}</div>
          </div>` : ''}

          ${rootCauses ? `
          <div class=\"causes-section\">
            <div class=\"causes-title\">📊 根因分析</div>
            ${rootCauses}
          </div>` : ''}

          ${evidence ? `
          <div class=\"evidence-section\">
            <div class=\"evidence-title\">🔍 支撑证据</div>
            <div class=\"evidence-list\">${evidence}</div>
          </div>` : ''}

          ${suggestions ? `
          <div class=\"suggestions-section\">
            <div class=\"suggestions-title\">💡 后续建议</div>
            ${suggestions}
          </div>` : ''}
        `;

        detailsEl.appendChild(card);
      }
    }

    function filter() {
      const q = document.getElementById('q').value.toLowerCase();
      const sev = document.getElementById('sev').value;
      const filtered = allAnomalies.filter(a => {
        const text = [a.suite, a.case, a.metric, a.primary_reason].join(' ').toLowerCase();
        if (q && !text.includes(q)) return false;
        if (sev && a.severity !== sev) return false;
        return true;
      });
      renderTable(filtered);
      renderDetails(filtered);
    }

    // 事件监听
    document.getElementById('q').addEventListener('input', filter);
    document.getElementById('sev').addEventListener('change', filter);

    // 初始渲染
    renderTable(allAnomalies);
    renderDetails(allAnomalies);
  </script>
</body>
</html>
"""
    html = html.replace("[[TITLE]]", title)
    html = html.replace("[[TS]]", datetime.utcnow().isoformat() + "Z")
    html = html.replace("[[EMBED_JSON]]", embed_json)
    return html


def generate_report(run_dir: str, meta: dict, anomalies: list[dict[str, Any]], summary: dict) -> str:
    payload = {
        "meta": {
            "run_id": os.path.basename(run_dir),
            "date": meta.get("date"),
            "patch_id": meta.get("patch_id"),
            "patch_set": meta.get("patch_set"),
        },
        "summary": summary,
        "anomalies": anomalies,
    }
    embed_json = json.dumps(payload, ensure_ascii=False)
    html = _html_template(
        embed_json, title=f"UB Report - {payload['meta']['run_id']}")
    out_path = os.path.join(run_dir, "report.html")
    write_text(out_path, html)
    return out_path
