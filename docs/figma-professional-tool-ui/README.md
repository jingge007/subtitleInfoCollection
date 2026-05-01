# subtitleInfoCollection - Professional Tool UI

Figma file created:

- Name: `subtitleInfoCollection - Professional Tool UI`
- Team: `jing jing's team`
- URL: https://www.figma.com/design/97LLcGvppgQ4lhh0NCbUt5
- File key: `97LLcGvppgQ4lhh0NCbUt5`

The Figma MCP connector hit the Starter-plan tool-call limit immediately after the blank file was created, so no nodes could be written into the file during this run.

## Prepared Figma Build Script

`figma-use-script.js` is a complete Figma Plugin API / `use_figma` script that builds the planned file structure:

- `01 Audit`: current UI structure, visual issues, and implementation invariants.
- `02 Design System`: light Ops palette, compact typography, buttons, inputs, badges, tables, cards, and log panels.
- `03 Screens`: 1440px desktop flow frames for dashboard, collection, parsing, history, and maintenance.

When the connector quota is available again, run the script against file key `97LLcGvppgQ4lhh0NCbUt5` with:

- `skillNames`: `figma-use,figma-generate-design`
- `description`: `Build subtitleInfoCollection professional tool UI design pages`

The script uses real current product labels from `src/subtitle_info_collection/gui/main_window.py` and preserves the implementation mapping:

- Main code target: `src/subtitle_info_collection/gui/main_window.py`
- Keep unchanged: `AppStorage.task_center_summary()`, `evaluate_config()`, worker signals, collector/parser business logic.
- UI-only changes later: helper widgets, object names, stylesheet, and layout structure.

## Local Verification

`preview.html` is a local high-fidelity browser preview of the same planned design. It covers the audit, design system, dashboard states, collection states, parser, history, and maintenance screens so the UI direction can be reviewed before the Figma connector quota is available again.

Verification completed locally:

- `figma-use-script.js` was syntax-checked by compiling it as an async function body.
- `preview.html` was opened with Playwright Chromium at 1440x1100.
- Rendered preview checks: title found, 5 implementation-safe screen frames found, 14 action buttons found, 0 browser console errors.
- Screenshot: `preview-screenshot.png`.

Visual Figma screenshots could not be taken because the MCP quota error blocked all Figma write/read calls after file creation.
