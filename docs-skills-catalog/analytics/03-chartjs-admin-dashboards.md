# Chart.js Admin Dashboards

**Category:** Analytics
**Related:** `analytics/01-first-party-page-view-tracker.md`, `analytics/02-device-browser-os-breakdown.md`

## When to use
You need rich charts (line, stacked bar, donut, KPI cards) inside an admin
dashboard that's just server-rendered HTML — no React, no Vite, no build
step. Chart.js + a CDN tag + a handful of `new Chart(ctx, {...})` calls is
the lightest path.

## Architecture
- Chart.js loaded from CDN once in the admin shell:
  `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`
  (single `<script>` tag at `templates/admin/dashboard.html:10537`).
- Each chart is a vanilla JS function:
  - Fetches its data from a `/admin/api/*` endpoint
  - Destroys the previous `Chart` instance if it exists (Chart.js
    leaks if you re-init over the same canvas)
  - Renders into a `<canvas>` element with explicit pixel size set
    via the parent's CSS (Chart.js auto-scales by `devicePixelRatio`)
- KPI cards are plain `<div>` tiles with big numbers — Chart.js isn't
  used for those, they're just CSS.
- Tabs that don't render charts on first paint should init lazily on
  tab activation so closed tabs don't burn CPU.

## Chart types in use
- **Line** — traffic over time, cost over time (used in
  `renderAnalyticsChart`, `_costSeriesChart`).
- **Stacked bar** — per-day breakdown by surface (chat / voice /
  SMS spend stacked per day in the Cost tab).
- **Donut / Pie** — browser / OS / device share.
- **KPI tiles** — CSS, not Chart.js.

## Data shape
Server endpoints return `{labels: [...], datasets: [{label, data, ...}]}`
which is exactly what Chart.js expects, so no client transform needed:
```
{
  "labels": ["2026-05-01", "2026-05-02", ...],
  "datasets": [
    {"label": "Views",   "data": [120, 180, ...]},
    {"label": "Visitors","data": [40, 60, ...]}
  ]
}
```

## Key files
- `templates/admin/dashboard.html:10537` — Chart.js CDN tag
- `templates/admin/dashboard.html:15652` — `renderAnalyticsChart` (line)
- `templates/admin/dashboard.html:17412` — `__overviewTrendChart` (line)
- `templates/admin/dashboard.html:19159` — `__widgetCharts` (mix)
- `templates/admin/dashboard.html:24060` — `_costSeriesChart` (stacked bar)

## External deps
- Chart.js 4.x via jsdelivr CDN. No build step.
- Optional: `chartjs-adapter-date-fns` if you want time-axis charts
  with auto-tick formatting.

## Pitfalls
- **Always destroy the prior instance** before re-rendering, or canvases
  pile up handlers and memory leaks:
  ```js
  if (window._myChart) window._myChart.destroy();
  window._myChart = new Chart(ctx, {...});
  ```
- Don't set `<canvas width height>` HTML attributes — set CSS on the
  parent `<div>`. Chart.js will handle DPR scaling.
- Pinned versions matter: 4.x and 3.x have incompatible plugin APIs.
- For stacked bars, set both axes' `stacked: true`. Forgetting one
  axis gives you regular grouped bars with no error.
- Tooltips have a default `mode: 'nearest'` that flickers on dense
  data — switch to `mode: 'index'` for line charts.
- Time-range filters must be applied server-side; sending 90 days of
  raw rows and filtering client-side will eventually OOM the tab.

## Adaptation notes
- For a React/Vite stack, use `react-chartjs-2` instead — same Chart.js
  under the hood.
- For thousands of points, enable Chart.js's decimation plugin
  (`options.plugins.decimation`).
- Dark mode: set `Chart.defaults.color`, `Chart.defaults.borderColor`,
  and per-dataset colors at startup based on your CSS variables.
- Export to PNG with `chart.toBase64Image()` for "Download chart" buttons.

## Adoption checklist
1. Add the Chart.js CDN tag once in your admin shell.
2. Build endpoints that return `{labels, datasets}` (the Chart.js shape).
3. For each chart: a `<canvas id="...">`, a render function, a
   `chart.destroy()` guard, and a tab-activation hook to init lazily.
4. Centralise color tokens (gold accent, danger red, etc.) in one
   `CHART_COLORS` object so palettes stay consistent.
