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
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, PingFang SC, Helvetica, Arial, sans-serif; margin: 16px; }
    h1 { font-size: 20px; margin: 8px 0; }
    h2 { font-size: 16px; margin: 12px 0 6px; }
    .summary { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; overflow: hidden; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
    th { background: #f5f5f5; }
    .sev-high { color: #b71c1c; font-weight: 700; }
    .sev-medium { color: #e65100; font-weight: 700; }
    .sev-low { color: #33691e; font-weight: 700; }
    .muted { color: #666; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
    .footer { color: #888; font-size: 12px; margin-top: 24px; }
    .filter-bar { display: flex; gap: 8px; margin: 8px 0; align-items: center; }
    input, select { padding: 6px 8px; border: 1px solid #ccc; border-radius: 6px; }
    .pill { padding: 2px 8px; border-radius: 999px; background: #efefef; font-size: 12px; }
    pre { white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <h1>UB 异常分析报告</h1>
  <div id=\"meta\" class=\"muted\"></div>
  <div class=\"summary\" id=\"summary\"></div>
  <div class=\"filter-bar\">
    <label>筛选:</label>
    <input id=\"q\" placeholder=\"suite/case/metric...\" />
    <select id=\"sev\">
      <option value=\"\">所有严重级</option>
      <option value=\"high\">high</option>
      <option value=\"medium\">medium</option>
      <option value=\"low\">low</option>
    </select>
  </div>
  <div class=\"card\">
    <table id=\"anom-table\">
      <thead><tr>
        <th>suite</th><th>case</th><th>metric</th><th>value</th><th>状态</th>
        <th>严重级</th><th>置信度</th><th>原因</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <h2>详细</h2>
  <div class=\"grid\" id=\"cards\"></div>

  <div class=\"footer\">Generated at [[TS]]</div>

  <script id=\"report-data\" type=\"application/json\">[[EMBED_JSON]]</script>
  <script>
    const data = JSON.parse(document.getElementById('report-data').textContent);
    const metaEl = document.getElementById('meta');
    metaEl.textContent = `run_id: ${data.meta.run_id} | date: ${data.meta.date} | patch: ${data.meta.patch_id}/${data.meta.patch_set}`;

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

    const summaryEl = document.getElementById('summary');
    const s = data.summary || { total_anomalies: (data.anomalies||[]).length, severity_counts: {} };
    summaryEl.innerHTML = `
      <div class='card'>总异常 <span class='pill'>${s.total_anomalies}</span></div>
      <div class='card'>high <span class='pill'>${(s.severity_counts||{}).high || 0}</span></div>
      <div class='card'>medium <span class='pill'>${(s.severity_counts||{}).medium || 0}</span></div>
      <div class='card'>low <span class='pill'>${(s.severity_counts||{}).low || 0}</span></div>
    `;

    const tbody = document.querySelector('#anom-table tbody');
    const cards = document.getElementById('cards');
    const all = data.anomalies || [];

    function render(list){
      tbody.innerHTML='';
      cards.innerHTML='';
      for(const a of list){
        const tr = document.createElement('tr');
        const status = a.severity ? '异常' : '正常';
        tr.innerHTML = `
          <td>${a.suite||''}</td>
          <td>${a.case||''}</td>
          <td>${a.metric||''}</td>
          <td>${fmtVal(a.current_value)}</td>
          <td>${status}</td>
          <td class='${sevClass(a.severity)}'>${a.severity||''}</td>
          <td>${fmtConf(a.confidence)}</td>
          <td>${a.primary_reason||''}</td>
        `;
        tbody.appendChild(tr);

        const card = document.createElement('div');
        card.className = 'card';
        const rc = (a.root_causes||[]).map(rc=>`<li>${rc.cause||''} (${fmtConf(rc.likelihood)})</li>`).join('');
        const se = a.supporting_evidence ? `<pre class='muted'>${JSON.stringify(a.supporting_evidence,null,2)}</pre>` : '';
        const nxt = (a.suggested_next_checks||[]).map(x=>`<li>${x}</li>`).join('');
        card.innerHTML = `
          <div><b>${a.suite||''} / ${a.case||''} / ${a.metric||''}</b></div>
          <div class='${sevClass(a.severity)}'>严重级: ${a.severity||''}，置信度: ${fmtConf(a.confidence)}</div>
          <div>原因: ${a.primary_reason||''}</div>
          ${rc?`<div><b>根因假设</b><ul>${rc}</ul></div>`:''}
          ${se}
          ${nxt?`<div><b>后续建议</b><ul>${nxt}</ul></div>`:''}
        `;
        cards.appendChild(card);
      }
    }

    const q = document.getElementById('q');
    const sev = document.getElementById('sev');
    function applyFilter(){
      const needle = (q.value||'').toLowerCase();
      const s = sev.value;
      const filtered = all.filter(a=>{
        const blob = `${a.suite||''} ${a.case||''} ${a.metric||''}`.toLowerCase();
        const okText = !needle || blob.includes(needle);
        const okSev = !s || a.severity === s;
        return okText && okSev;
      });
      render(filtered);
    }
    q.addEventListener('input', applyFilter);
    sev.addEventListener('change', applyFilter);
    render(all);
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
