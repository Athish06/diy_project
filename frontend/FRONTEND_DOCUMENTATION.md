# Frontend High-Level Documentation

Simple view of what is inside `frontend/` and what each file is for.

## Root Files

- `frontend/index.html`: Main HTML shell used by Vite.
- `frontend/package.json`: Frontend scripts and npm dependencies.
- `frontend/package-lock.json`: Locked dependency versions.
- `frontend/postcss.config.js`: PostCSS setup (used with Tailwind).
- `frontend/tailwind.config.js`: Tailwind theme/content configuration.
- `frontend/tsconfig.json`: TypeScript compiler settings.
- `frontend/vite.config.ts`: Vite build/dev server config.
- `frontend/tsconfig.tsbuildinfo`: TypeScript incremental build cache file.
- `frontend/node_modules/`: Installed npm packages (generated, not app code).

## `src/` Main Files

- `frontend/src/main.tsx`: App bootstrap and React render entrypoint.
- `frontend/src/App.tsx`: Main app-level layout and routing composition.
- `frontend/src/globals.css`: Global CSS styles.

## `src/components/`

- `AnalysisProgress.tsx`: Shows analysis progress state.
- `ComparisonTable.tsx`: Displays model/report comparison table.
- `ComplianceVerdict.tsx`: Shows compliance/safety verdict section.
- `DiyForm.tsx`: Input form for DIY video analysis.
- `DiyStepCard.tsx`: UI card for one extracted DIY step.
- `DiyStepsContainer.tsx`: Container/list for all DIY steps.
- `Header.tsx`: Main header area.
- `LeftSidebar.tsx`: Left side panel layout.
- `ModelResultsTabs.tsx`: Tabbed view for model outputs.
- `ParticleCanvas.tsx`: Visual background/particle effect component.
- `RightPanel.tsx`: Right side panel layout.
- `SafetyRulesTable.tsx`: Table for matched safety rules.
- `SettingsPanel.tsx`: UI for app settings/options.
- `TopBar.tsx`: Top navigation/status bar.
- `VerdictCard.tsx`: Compact verdict summary card.
- `VideoInfo.tsx`: Video metadata display (title/channel/etc.).

## `src/constants/`

- `index.ts`: Shared constants used across frontend.

## `src/contexts/`

- `ExtractionContext.tsx`: React context for extraction/analysis state.
- `ThemeContext.tsx`: React context for theme state.

## `src/hooks/`

- `useDiyAnalysis.ts`: Custom hook to run/manage DIY analysis logic.

## `src/lib/`

- `api.ts`: API helper functions for backend communication.

## `src/pages/`

- `HistoryPage.tsx`: Page showing previous scans/history.
- `SafetyPage.tsx`: Page focused on safety/rules view.

## `src/types/`

- `index.ts`: Shared frontend TypeScript types.
- `safety.ts`: Safety-specific TypeScript types.

## `src/utils/`

- `video.ts`: Video-related utility helpers (for IDs/URLs/etc.).