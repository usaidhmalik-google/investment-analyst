---
name: fde-ui-designer
description: >-
  Builds, refactors, and declutters enterprise web UIs, dashboards, human-in-the-loop review workbenches, operational triage queues, NL2SQL explorers, and Gemini Enterprise MCP Apps using Google Cloud Console and Material Design 3 standards. Use when asked to build a dashboard or prototype UI, create an HTML/CSS/JS or React frontend for an agent or JSON payload, add features to an existing workbench, make a UI look better or executive-ready, declutter a messy prototype, or fix layout, alignment, and contrast issues. Don't use for matching an external company's custom brand design system, declarative A2UI v0.9 JSON cards (use fde-gemini-enterprise-a2ui), or static architecture diagrams (use ai-fde-architecture-diagrams).
---

# FDE UI Designer — Master CSS Style Guide & Rule of 3

Build clean, scannable, executive-ready web UIs and Gemini Enterprise MCP Apps grounded in Google Cloud Console and Material Design 3. Copy the Master Stylesheet in Section 2 verbatim and enforce the **Rule of 3**.

## 1. The Rule of 3

### 1.1 One Font, Zero Emojis & Three Sizes (`Small`, `Medium`, `Large`)
- **1 Font & Tabular Numerals**: Use `--font-sans` (`Roboto`) globally and `tabular-nums` on all tables, numbers, dates, currencies, and code. Right-align numeric table columns (`class="is-num"` on `<th>` and `<td>`).
- **0 Emojis, 0 External Icon Fonts, 0 Raw Hexes**: Never use Unicode emojis, `<link>` icon fonts (`Material Symbols`), or raw `#hex` colors outside `:root`. Use the 6 inline SVGs in Section 2.1.
- **3 Locked Sizes** (`0` sub-pixel font sizes, `0` ad-hoc spacing tokens):

| Dimension | Small (`sm`) | Medium (`md` — Default) | Large (`lg`) |
| :--- | :--- | :--- | :--- |
| **Typography** | `--text-sm: 12px` (`16px` line)<br>Eyebrows, `.ui-badge`, `th`, `code`/`pre` | `--text-md: 14px` (`20px` line)<br>Body, buttons, inputs, `td` | `--text-lg: 16px` (`24px` line)<br>`h1`/`h2` titles, primary KPIs |
| **Spacing (`4px` grid)** | `--space-sm: 8px` (inline/compact gap) | `--space-md: 16px` (card/bar pad) | `--space-lg: 24px` (canvas/sheet pad) |
| **Heights** | `--height-sm: 32px` (buttons, inputs, `.ui-segmented`) | `--height-md: 40px` (`th`/`td` rows, `summary`) | `--height-lg: 48px` (`.ui-topbar`, `.ui-toolbar`) |
| **Widths** | `--width-sm: 320px` (`.ui-sidebar` rail) | `--width-md: 512px` (form/inspector) | `--width-lg: 768px` (detail container) |
| **Radius & Shadow** | `--radius-sm: 4px`, flat (`--radius-pill: 999px` badges) | `--radius-md: 8px`, `--shadow-sm` (cards/tables) | `--radius-lg: 12px`, `--shadow-md` (`.ui-sheet`) |

### 1.2 Three Color Roles (60-30-10 Palette)
Reference all colors via `:root` variables (`>= 4.7:1` WCAG AA text contrast):
1. **60% Surface**: `--bg-app` (workspace), `--bg-surface` (cards/sheets/tables), `--bg-subtle` (headers/tracks/code), `--bg-active` (selected card), `--border` (`1px` dividers).
2. **30% Ink**: `--text-primary` (body/headings) and `--text-secondary` (labels/metadata).
3. **10% Accent & Semantic Status**: `--primary` (`1` primary CTA + active states) and `--success` / `--warning` / `--danger` (reserved strictly for low-confidence `< 0.80` or exception states—never decorate normal rows).

### 1.3 Three Focal Points (Viewport Layout & Scanline Discipline)
Never create 3+ side-by-side columns, multi-card sub-grids, top KPI hero banners, or bottom chat bars:
1. **Top App Bar (`.ui-topbar`, `48px` single row)**: Left `.ui-row` holds `<h1>` (always first child) + max `1` `.ui-badge` status pill; right `.ui-row` holds max `1` `.ui-segmented` switcher (`<= 3` options) + `1` `.ui-btn--primary` CTA (`<= 5` controls per bar).
2. **Context Sidebar (`.ui-sidebar`, `320px`)**: Left queue/filter/notes rail (`16px` padding). Preserve DOM input state (`hidden` attribute) when switching tabs.
3. **Primary Work Canvas (`.ui-canvas`, `>= 60%` viewport)**: Single vertical column of `.ui-sheet` or `.ui-card` blocks (`<= 4` distinct left-edge X scanlines at `1280×800`). At `<= 680px` (`480×600` PiP / `375×667` mobile), `.ui-sidebar` caps at `max-height: 180px !important` so `.ui-canvas` stays above the fold (`top < 260px`) with `0` horizontal overflow.

### 1.4 Three Component, Disclosure & Hygiene Rules
1. **3 Button Variants & `32px` Row Lock**: Use **only** `.ui-btn`, `.ui-btn--primary`, and `.ui-btn--danger` (`32px` height). Wrap tab/mode toggles in `.ui-segmented`. Max `2` action buttons per card inside `.ui-card-actions` (2-column grid so `Approve` / `Reject` never wrap). Never put `role="button"` or `data-id` on inline `<mark>`/`<span>` text, and never mix `<input>` fields and action buttons in the same unwrapped row.
2. **3-Layer Progressive Disclosure**:
   - **Layer 1**: Chronological overview (*before* recommendations) or `<pre>` SQL block (`3px` primary left border).
   - **Layer 2**: `tabular-nums` `<table>` (`40px` rows, `th.is-num, td.is-num`) or callout. Use `.ui-meter` only for `0–100%` ratios.
   - **Layer 3**: **Collapsed-by-default** `<details class="ui-disclosure">` for execution traces, audit tables, and raw JSON.
3. **Data Hygiene, Batching & Brownfield Subtraction**:
   - **Sanitize**: Never render literal `null`, `NaN`, `undefined`, raw `EVENT_*` enums, or internal debug keys (`diagnosticInfos`, `gemini-3.1-flash-live`). Format missing values as `Not Reported` or `—`.
   - **Exception-First & Batching**: Suppress any badge repeated on `> 75%` of cards; group duplicate entities (`>= 2`) into one card with `Approve All (N)` / `Reject All (N)` (and include a bulk `Approve All` action in review queues); default queues to `< 0.80` confidence exceptions; gate external tool triggers (`disabled`) behind Step 1 verification.
   - **Brownfield & MCP Handshake**: Preserve existing DOM IDs, strip top KPI banners, extra card buttons (`Delete Box`, `Split Box`), and external font `<link>`s, and emit `window.parent.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {} }, '*');` on load.

---

## 2. Master Global CSS Style Guide (Copy Verbatim into `<style>`)

```css
:root {
  --font-sans: 'Roboto', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  --text-sm: 12px;   --text-md: 14px;   --text-lg: 16px;
  --space-sm: 8px;   --space-md: 16px;  --space-lg: 24px;  --btn-pad-x: 12px;
  --height-sm: 32px; --height-md: 40px; --height-lg: 48px;
  --width-sm: 320px; --width-md: 512px; --width-lg: 768px;
  --radius-sm: 4px;  --radius-md: 8px;  --radius-lg: 12px; --radius-pill: 999px;
  --shadow-sm: 0 1px 2px rgba(32, 33, 36, 0.06), 0 1px 3px rgba(32, 33, 36, 0.04);
  --shadow-md: 0 2px 6px rgba(32, 33, 36, 0.08), 0 1px 2px rgba(32, 33, 36, 0.05);
  --bg-app: #F8F9FA;     --bg-surface: #FFFFFF; --bg-subtle: #F1F3F4;
  --bg-active: #F4F8FE;  --border: #DADCE0;
  --text-primary: #202124; --text-secondary: #5F6368;
  --primary: #1967D2;    --primary-hover: #1557B0; --primary-tonal: #E8F0FE; --on-primary: #FFFFFF;
  --success-bg: #E6F4EA; --success-text: #137333;
  --warning-bg: #FEF7E0; --warning-text: #B06000;
  --danger-bg: #FCE8E6;  --danger-text: #C5221F;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  width: 100%; height: 100%; overflow-x: hidden;
  background: var(--bg-app); color: var(--text-primary);
  font-family: var(--font-sans); font-size: var(--text-md); line-height: 20px;
  -webkit-font-smoothing: antialiased; display: flex; flex-direction: column;
}

h1, h2, .text-lg { font-size: var(--text-lg); line-height: 24px; font-weight: 600; letter-spacing: -0.01em; color: var(--text-primary); }
h3, p, li, td, label, .text-md { font-size: var(--text-md); line-height: 20px; }
h3 { font-weight: 600; letter-spacing: -0.005em; }
small, th, code, pre, .text-sm, .ui-eyebrow, .ui-badge { font-size: var(--text-sm); line-height: 16px; }
.ui-eyebrow, th { font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-secondary); }
.text-secondary { color: var(--text-secondary); }
code, pre { font-family: var(--font-sans); font-variant-numeric: tabular-nums; }

pre {
  background: var(--bg-subtle); border: 1px solid var(--border); border-left: 3px solid var(--primary);
  border-radius: var(--radius-sm); padding: var(--space-sm) var(--space-md); overflow-x: auto; white-space: pre-wrap;
}

mark, .ui-mark {
  background: var(--primary-tonal); color: var(--primary); border-bottom: 2px solid var(--primary);
  border-radius: 2px; padding: 0 4px; font-weight: 500; font-variant-numeric: tabular-nums;
}

table {
  width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums;
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden;
}
th, td { height: var(--height-md); padding: 0 var(--space-md); text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--bg-subtle); white-space: nowrap; }
th.is-num, td.is-num { text-align: right; font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }

.ui-topbar {
  min-height: var(--height-lg); padding: var(--space-sm) var(--space-lg);
  background: var(--bg-surface); border-bottom: 1px solid var(--border); box-shadow: var(--shadow-sm);
  position: relative; z-index: 10; display: flex; align-items: center; justify-content: space-between;
  flex-wrap: nowrap; gap: var(--space-md);
}
.ui-topbar > .ui-row { flex-wrap: nowrap; min-width: 0; }
.ui-topbar h1 { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.ui-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: var(--width-sm) minmax(0, 1fr); overflow: hidden; }
.ui-workspace.is-collapsed { grid-template-columns: var(--height-lg) minmax(0, 1fr); }
.ui-sidebar { background: var(--bg-surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; min-width: 0; }
.ui-canvas { background: var(--bg-app); display: flex; flex-direction: column; overflow-y: auto; min-width: 0; padding: var(--space-lg); gap: var(--space-md); }

.ui-toolbar {
  min-height: var(--height-lg); padding: var(--space-sm) var(--space-md);
  background: var(--bg-surface); border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--space-sm);
}

.ui-card {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: var(--space-md); box-shadow: var(--shadow-sm); display: flex; flex-direction: column; gap: var(--space-sm);
  transition: border-color 120ms ease, box-shadow 120ms ease, background-color 120ms ease;
}
.ui-card.is-active {
  border-color: var(--primary); background: var(--bg-active);
  box-shadow: inset 3px 0 0 var(--primary), var(--shadow-sm);
}

.ui-sheet {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: var(--space-lg); box-shadow: var(--shadow-md); display: flex; flex-direction: column; gap: var(--space-md);
}

.ui-row { display: flex; align-items: center; gap: var(--space-sm); flex-wrap: wrap; }
.ui-card-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-sm); width: 100%; }
.ui-card-actions > button, .ui-card-actions > .ui-btn { width: 100%; min-width: 0; padding: 0 var(--space-sm); }

.ui-disclosure { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); box-shadow: var(--shadow-sm); overflow: hidden; }
.ui-disclosure > summary {
  height: var(--height-md); padding: var(--space-md); display: flex; align-items: center; justify-content: space-between;
  font-size: var(--text-md); font-weight: 500; color: var(--text-secondary); cursor: pointer; list-style: none; user-select: none;
}
.ui-disclosure > summary::-webkit-details-marker { display: none; }
.ui-disclosure > summary::after {
  content: ''; width: 6px; height: 6px; border-right: 1.5px solid var(--text-secondary); border-bottom: 1.5px solid var(--text-secondary);
  transform: rotate(-45deg); transition: transform 150ms ease; margin-left: var(--space-sm);
}
.ui-disclosure[open] > summary::after { transform: rotate(45deg); }
.ui-disclosure-body { padding: var(--space-md); border-top: 1px solid var(--border); background: var(--bg-subtle); }

button, input, select, [role="button"], .ui-btn {
  height: var(--height-sm); min-height: var(--height-sm); max-height: var(--height-sm);
  padding: 0 var(--btn-pad-x); border-radius: var(--radius-sm); border: 1px solid var(--border);
  background: var(--bg-surface); color: var(--text-primary); font-family: var(--font-sans);
  font-size: var(--text-md); line-height: 30px; white-space: nowrap;
  transition: background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}
button, [role="button"], .ui-btn { font-weight: 500; display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer; }
input { font-weight: 400; text-align: left; cursor: text; }
select { font-weight: 500; text-align: left; cursor: pointer; }
button:hover:not([disabled]), .ui-btn:hover:not([disabled]) { background: var(--bg-subtle); }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }

textarea {
  width: 100%; padding: var(--space-sm) var(--btn-pad-x); border-radius: var(--radius-sm);
  border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-primary);
  font-family: var(--font-sans); font-size: var(--text-md); line-height: 20px; cursor: text;
}

.ui-btn--primary { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.ui-btn--primary:hover:not([disabled]) { background: var(--primary-hover); border-color: var(--primary-hover); }
.ui-btn--danger { background: var(--danger-bg); border-color: var(--danger-bg); color: var(--danger-text); }
.ui-btn--danger:hover:not([disabled]) { background: var(--danger-bg); border-color: var(--danger-text); }
button[disabled], .ui-btn[disabled] { background: var(--bg-subtle); border-color: var(--border); color: var(--text-secondary); cursor: not-allowed; }

.ui-segmented {
  height: var(--height-sm); display: inline-flex; align-items: center; gap: 2px; padding: 1px;
  background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius-md); max-width: 100%;
}
.ui-sidebar .ui-segmented { display: flex; width: 100%; }
.ui-segmented > .ui-btn {
  height: 28px; min-height: 28px; max-height: 28px; line-height: 26px; padding: 0 var(--space-sm);
  flex: 1 1 auto; border-color: transparent; background: transparent; color: var(--text-secondary);
}
.ui-segmented > .ui-btn.is-active, .ui-segmented > .ui-btn[aria-pressed="true"], .ui-segmented > .ui-btn[aria-selected="true"] {
  background: var(--bg-surface); color: var(--primary); border-color: var(--border); box-shadow: var(--shadow-sm);
}

.ui-badge {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px var(--space-sm);
  border-radius: var(--radius-pill); font-size: var(--text-sm); font-weight: 500;
  background: var(--bg-subtle); color: var(--text-secondary); white-space: nowrap;
}
.ui-badge::before { content: ''; width: 6px; height: 6px; border-radius: var(--radius-pill); background: currentColor; flex-shrink: 0; }
.ui-badge--primary { background: var(--primary-tonal); color: var(--primary); }
.ui-badge--success { background: var(--success-bg); color: var(--success-text); }
.ui-badge--warning { background: var(--warning-bg); color: var(--warning-text); }
.ui-badge--danger  { background: var(--danger-bg); color: var(--danger-text); }

.ui-meter { width: 100%; height: 4px; background: var(--bg-subtle); border-radius: var(--radius-pill); overflow: hidden; }
.ui-meter > span { display: block; height: 100%; background: var(--primary); border-radius: var(--radius-pill); }
.ui-meter--success > span { background: var(--success-text); }
.ui-meter--warning > span { background: var(--warning-text); }
.ui-meter--danger > span  { background: var(--danger-text); }

.ui-icon { width: 14px; height: 14px; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; fill: none; flex-shrink: 0; }

@media (max-width: 680px) {
  html, body { height: auto; }
  .ui-topbar { padding: var(--space-sm) var(--space-md); flex-wrap: wrap; gap: var(--space-sm); }
  .ui-topbar > .ui-row { flex-wrap: wrap; }
  .ui-workspace, .ui-workspace.is-collapsed { grid-template-columns: 1fr; height: auto; overflow: visible; }
  .ui-sidebar { max-height: 180px !important; border-right: none; border-bottom: 1px solid var(--border); }
  .ui-canvas, .ui-sheet { padding: var(--space-md); }
  table { display: block; width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  th, td { white-space: nowrap; }
}
```

### 2.1 Six Offline Inline SVG Micro-Icons
- **Check (`Approve`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>`
- **Close (`Reject`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
- **Export (`Download`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`
- **Warning (`Alert`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
- **Refresh (`Undo`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`
- **Edit (`Draw / Re-key`)**: `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`

---

## 3. Pre-Finish Verification Checklist
1. **Zero Emojis, Zero External Icon Fonts & MCP Handshake**: `0` emojis, `0` external icon font `<link>`s, and `ui/notifications/initialized` `postMessage` present.
2. **Master CSS Token Compliance**: Only `12px`/`14px`/`16px` font sizes (`0` sub-pixel values), `<= 3` button classes (`.ui-btn`, `.ui-btn--primary`, `.ui-btn--danger`), `0` undeclared CSS variables, and `0` raw `#hex` colors outside `:root`.
3. **Row Alignment & Action Density**: All `<button>`, `<input>`, `<select>`, and `.ui-segmented` controls are `32px` tall; `<= 5` controls per bar; `<= 2` action buttons per card inside `.ui-card-actions`.
4. **Data & Responsive Hygiene**: `0` visible `null`/`NaN`/`undefined`/raw `EVENT_*` strings; `tabular-nums` + `is-num` on tables; primary canvas `>= 60%` desktop area and above the fold (`top < 260px`) at `480×600` PiP and `375×667` mobile.
