# Base Family Office HTML Template (Executive Summary + Deep Dive)

```html
<div style="font-family:'Avenir Next','Segoe UI',Arial,sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#182026;line-height:1.45;background:#ffffff;">
  <div style="background:linear-gradient(135deg,{{accent}} 0%,{{accent_dark}} 100%);color:#ffffff;padding:16px 18px;border-radius:10px;margin-bottom:14px;">
    <div style="font-size:11px;letter-spacing:1.2px;text-transform:uppercase;opacity:0.9;">{{persona_label}}</div>
    <div style="font-size:18px;font-weight:700;margin-top:4px;">{{subject_line}}</div>
    <div style="font-size:13px;opacity:0.9;margin-top:4px;">{{subline}}</div>
  </div>

  <h3 style="margin:0 0 8px 0;font-size:14px;color:{{accent}};border-bottom:2px solid {{accent}};padding-bottom:4px;">Executive Summary (2-Minute Scan)</h3>
  <p style="margin:0 0 10px 0;font-size:13px;color:#2d3a45;">{{exec_summary_text}}</p>

  <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 14px 0;">
    <div style="border:1px solid #d9e2ec;border-radius:8px;padding:10px;background:#f8fbff;">
      <div style="font-size:11px;color:#52606d;text-transform:uppercase;letter-spacing:0.8px;">{{kpi_1_label}}</div>
      <div style="font-size:20px;font-weight:700;color:{{accent}};margin-top:2px;">{{kpi_1_value}}</div>
      <div style="font-size:11px;color:#6b7785;">{{kpi_1_delta}}</div>
    </div>
    <div style="border:1px solid #d9e2ec;border-radius:8px;padding:10px;background:#f8fbff;">
      <div style="font-size:11px;color:#52606d;text-transform:uppercase;letter-spacing:0.8px;">{{kpi_2_label}}</div>
      <div style="font-size:20px;font-weight:700;color:{{accent}};margin-top:2px;">{{kpi_2_value}}</div>
      <div style="font-size:11px;color:#6b7785;">{{kpi_2_delta}}</div>
    </div>
    <div style="border:1px solid #d9e2ec;border-radius:8px;padding:10px;background:#f8fbff;">
      <div style="font-size:11px;color:#52606d;text-transform:uppercase;letter-spacing:0.8px;">{{kpi_3_label}}</div>
      <div style="font-size:20px;font-weight:700;color:{{accent}};margin-top:2px;">{{kpi_3_value}}</div>
      <div style="font-size:11px;color:#6b7785;">{{kpi_3_delta}}</div>
    </div>
  </div>

  <h3 style="margin:0 0 8px 0;font-size:14px;color:{{accent}};border-bottom:2px solid {{accent}};padding-bottom:4px;">Action Board</h3>
  <table style="border-collapse:collapse;width:100%;font-size:12.5px;margin-bottom:14px;">
    <tr>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Item</th>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Owner</th>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Due</th>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Status</th>
    </tr>
    {{action_rows}}
  </table>

  <h3 style="margin:0 0 8px 0;font-size:14px;color:{{accent}};border-bottom:2px solid {{accent}};padding-bottom:4px;">Primary Visual</h3>
  <div style="border:1px solid #d9e2ec;border-radius:8px;padding:10px;background:#fbfdff;margin-bottom:14px;">
    <div style="font-size:12px;color:#52606d;margin-bottom:8px;">{{primary_visual_caption}}</div>
    <div>
      {{primary_visual_html}}
    </div>
  </div>

  <h3 style="margin:0 0 8px 0;font-size:14px;color:{{accent}};border-bottom:2px solid {{accent}};padding-bottom:4px;">Deep Dive</h3>
  <div style="font-size:13px;color:#1f2933;margin-bottom:12px;">
    {{deep_dive_narrative_html}}
  </div>

  <h3 style="margin:0 0 8px 0;font-size:14px;color:{{accent}};border-bottom:2px solid {{accent}};padding-bottom:4px;">Data Provenance</h3>
  <table style="border-collapse:collapse;width:100%;font-size:12px;margin-bottom:14px;">
    <tr>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Claim / Metric</th>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Source System</th>
      <th style="background:#edf2f7;border:1px solid #d2dbe5;padding:7px 8px;text-align:left;">Tool / Link</th>
    </tr>
    {{provenance_rows}}
  </table>

  <p style="margin:0 0 10px 0;font-size:13px;">{{closing}}</p>

  <div style="font-size:11.5px;color:#5f6c7b;border-top:1px solid #e6ecf2;padding-top:10px;">
    {{signature_line}}<br>
    {{footer_line}}
  </div>
</div>
```

Usage notes:
- Executive Summary should remain fast to scan (KPI + Action Board + optional Primary Visual).
- Use one primary visual only when it materially improves the brief; otherwise omit the section rather than forcing a low-value chart.
- Choose the visual form that best explains the key point: spark trend, bar chart, line chart, scatter plot, progress bars, or another compact honest graphic.
- Deep Dive should explain reasoning, assumptions, and tradeoffs in plain language.
- Provenance table should name MCP tools and include web links when used.
- If no web sources were consulted, explicitly say so in Deep Dive or Provenance.
