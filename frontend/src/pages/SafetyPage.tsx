import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  fetchRules, fetchFilterOptions,
  fetchRulesByDocument, fetchExtractionRuns, runEvaluation,
} from '@/lib/api';
import { useTheme } from '@/contexts/ThemeContext';
import { useExtraction } from '@/contexts/ExtractionContext';
import type {
  DbRulesResponse, FilterOptions, DocumentCard,
  ExtractionRun, EvaluationResults,
  ExtractionProgressEvent, ExtractionStep,
} from '@/types/safety';

type ViewMode = 'rules' | 'runs';

/* ── Helpers ── */
const SEV_LABELS: Record<number, string> = { 5: 'Critical', 4: 'High', 3: 'Medium', 2: 'Low', 1: 'Info' };
const SEV_COLORS: Record<number, string> = {
  5: 'var(--color-unsafe)', 4: '#fb923c', 3: 'var(--color-caution)', 2: '#86efac', 1: '#6ee7b7',
};
const CHECK_LABELS: Record<string, string> = {
  text_presence: 'Text Presence', page_accuracy: 'Page Accuracy',
  heading_accuracy: 'Heading Accuracy', rule_structure: 'Rule Structure',
  category_validity: 'Category Validity', severity_consistency: 'Severity Consistency',
};

/* ── Chevron icon ── */
function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2"
      className={`transition-transform flex-shrink-0 ${open ? 'rotate-180' : ''}`}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

/* ────────────────────────────────────────────── */

export default function SafetyPage() {
  /* --- DB rules --- */
  const [dbRules, setDbRules] = useState<DbRulesResponse | null>(null);
  const [filters, setFilters] = useState<FilterOptions | null>(null);
  const [activeCategory, setActiveCategory] = useState('');
  const [activeSeverity, setActiveSeverity] = useState('');
  const [activeDocument, setActiveDocument] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [activeRunId, setActiveRunId] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [dbLoading, setDbLoading] = useState(true);
  const [dbError, setDbError] = useState<string | null>(null);
  const [rulesExpanded, setRulesExpanded] = useState(false);

  /* --- Document cards --- */
  const [docCards, setDocCards] = useState<DocumentCard[]>([]);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);

  /* --- Runs --- */
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [expandedRun, setExpandedRun] = useState<number | null>(null);
  const [runRules, setRunRules] = useState<DbRulesResponse | null>(null);
  const [runRulesLoading, setRunRulesLoading] = useState(false);
  const [runRulesExpanded, setRunRulesExpanded] = useState(false);
  const [evaluatingRunId, setEvaluatingRunId] = useState<number | null>(null);

  /* --- Extraction (from global context) --- */
  const {
    extracting, progressEvents, currentStep, extractError,
    startExtraction, dismissProgress,
  } = useExtraction();

  /* --- View mode --- */
  const [viewMode, setViewMode] = useState<ViewMode>('rules');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const PER_PAGE = 50;
  const { theme, toggleTheme } = useTheme();

  /* ── Load on mount ── */
  useEffect(() => {
    fetchFilterOptions().then(setFilters).catch(() => { });
    fetchRulesByDocument().then((d) => setDocCards(d.documents)).catch(() => { });
    fetchExtractionRuns().then((d) => setRuns(d.runs)).catch(() => { });
  }, []);

  /* ── Fetch rules ── */
  const loadRules = useCallback(async () => {
    setDbLoading(true);
    setDbError(null);
    try {
      const data = await fetchRules({
        category: activeCategory || undefined,
        severity: activeSeverity ? Number(activeSeverity) : undefined,
        document: activeDocument || undefined,
        search: activeSearch || undefined,
        run_id: activeRunId,
        page,
        perPage: PER_PAGE,
      });
      setDbRules(data);
    } catch (err) {
      setDbError(err instanceof Error ? err.message : String(err));
    } finally {
      setDbLoading(false);
    }
  }, [activeCategory, activeSeverity, activeDocument, activeSearch, activeRunId, page]);

  useEffect(() => { loadRules(); }, [loadRules]);

  /* ── Load runs ── */
  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const data = await fetchExtractionRuns();
      setRuns(data.runs);
    } catch { /* ignore */ } finally {
      setRunsLoading(false);
    }
  }, []);

  useEffect(() => { if (viewMode === 'runs') loadRuns(); }, [viewMode, loadRuns]);

  /* ── Expand run → load its rules ── */
  const handleExpandRun = useCallback(async (runId: number) => {
    if (expandedRun === runId) { setExpandedRun(null); setRunRules(null); setRunRulesExpanded(false); return; }
    setExpandedRun(runId);
    setRunRulesExpanded(false);
    setRunRulesLoading(true);
    try {
      const data = await fetchRules({ run_id: runId, perPage: 200 });
      setRunRules(data);
    } catch { setRunRules(null); } finally {
      setRunRulesLoading(false);
    }
  }, [expandedRun]);

  /* ── Trigger evaluation ── */
  const handleRunEvaluation = useCallback(async (runId: number) => {
    setEvaluatingRunId(runId);
    try {
      const result = await runEvaluation(runId);
      // Update the run in state
      setRuns((prev) =>
        prev.map((r) => r.id === runId ? { ...r, evaluation_results: result.evaluation_results } : r)
      );
    } catch { /* ignore */ } finally {
      setEvaluatingRunId(null);
    }
  }, []);

  /* ── Filters ── */
  const handleClearFilters = useCallback(() => {
    setActiveCategory(''); setActiveSeverity(''); setActiveDocument('');
    setActiveSearch(''); setActiveRunId(undefined); setExpandedDoc(null); setPage(1);
  }, []);

  const handleDocClick = useCallback((docName: string) => {
    if (expandedDoc === docName) {
      setExpandedDoc(null); setActiveDocument('');
    } else {
      setExpandedDoc(docName); setActiveDocument(docName);
    }
    setPage(1); setRulesExpanded(true);
  }, [expandedDoc]);

  /* ── Upload ── */
  const handleUploadClick = useCallback(() => { fileInputRef.current?.click(); }, []);

  const handleFilesSelected = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    const selectedFiles = Array.from(fileList);
    e.target.value = '';
    startExtraction(selectedFiles);
  }, [startExtraction]);

  // Reload data when extraction completes
  useEffect(() => {
    if (!extracting && progressEvents.length > 0 && currentStep === 'done') {
      loadRules();
      fetchFilterOptions().then(setFilters).catch(() => { });
      fetchRulesByDocument().then((d) => setDocCards(d.documents)).catch(() => { });
      loadRuns();
    }
  }, [extracting, currentStep, progressEvents.length, loadRules, loadRuns]);

  const totalPages = dbRules ? Math.max(1, Math.ceil(dbRules.total / PER_PAGE)) : 1;

  /* ──────────────────────── RENDER ──────────────────────── */
  return (
    <div className="safety-page-shell">
      <input ref={fileInputRef} type="file" accept=".pdf" multiple className="hidden" onChange={handleFilesSelected} />

      {/* ── Header ── */}
      <header className="safety-page-header">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-muted hover:text-foreground transition-colors" aria-label="Back">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
              </svg>
            </Link>
            <div>
              <h1 className="text-xl font-bold text-foreground">Safety Rules</h1>
              <p className="text-xs text-muted mt-0.5">Browse extracted rules or ingest new PDF rulebooks</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={toggleTheme} className="topbar-theme-toggle" title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              {theme === 'dark' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              )}
            </button>
            <button onClick={handleUploadClick} disabled={extracting} className="safety-upload-btn">
              {extracting ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Processing…
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  Add PDFs
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 px-6 pb-6 space-y-4">

        {/* ── Extraction Progress Panel ── */}
        {(extracting || progressEvents.length > 0) && (
          <ExtractionProgress
            events={progressEvents}
            currentStep={currentStep}
            extracting={extracting}
            error={extractError}
            onDismiss={dismissProgress}
          />
        )}
        {extractError && !extracting && progressEvents.length === 0 && (
          <div className="glass-card px-5 py-3 border-l-4" style={{ borderLeftColor: 'var(--color-unsafe)' }}>
            <p className="text-sm" style={{ color: 'var(--color-unsafe)' }}>{extractError}</p>
          </div>
        )}

        {/* ── Tabs ── */}
        <div className="flex gap-1 p-1 bg-input-bg rounded-lg w-fit">
          <button onClick={() => setViewMode('rules')}
            className={`px-4 py-1.5 text-sm rounded-md transition-all ${viewMode === 'rules'
              ? 'bg-card-bg text-foreground font-medium shadow-sm border border-card-border' : 'text-muted hover:text-foreground'}`}>
            All Rules {dbRules && <span className="ml-1.5 text-xs opacity-60">({dbRules.total})</span>}
          </button>
          <button onClick={() => setViewMode('runs')}
            className={`px-4 py-1.5 text-sm rounded-md transition-all ${viewMode === 'runs'
              ? 'bg-card-bg text-foreground font-medium shadow-sm border border-card-border' : 'text-muted hover:text-foreground'}`}>
            All Runs {runs.length > 0 && <span className="ml-1.5 text-xs opacity-60">({runs.length})</span>}
          </button>
        </div>

        {/* ════════════ ALL RULES VIEW ════════════ */}
        {viewMode === 'rules' && (
          <>
            {/* Filters bar */}
            <div className="glass-card px-5 py-4">
              <div className="flex flex-wrap gap-3 items-end">
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Category</label>
                  <select value={activeCategory} onChange={(e) => { setActiveCategory(e.target.value); setPage(1); }} className="safety-select">
                    <option value="">All Categories</option>
                    {filters?.categories.map((cat) => <option key={cat} value={cat}>{cat}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Severity</label>
                  <select value={activeSeverity} onChange={(e) => { setActiveSeverity(e.target.value); setPage(1); }} className="safety-select">
                    <option value="">All Severities</option>
                    {filters?.severities.map((sev) => <option key={sev} value={sev}>{sev} — {SEV_LABELS[sev] ?? sev}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Document</label>
                  <select value={activeDocument} onChange={(e) => { setActiveDocument(e.target.value); setExpandedDoc(e.target.value || null); setPage(1); }} className="safety-select">
                    <option value="">All Documents</option>
                    {filters?.documents.map((doc) => <option key={doc} value={doc}>{doc}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Run</label>
                  <select value={activeRunId ?? ''} onChange={(e) => { setActiveRunId(e.target.value ? Number(e.target.value) : undefined); setPage(1); }} className="safety-select">
                    <option value="">All Runs</option>
                    {runs.map((run) => <option key={run.id} value={run.id}>Run #{run.id}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Search</label>
                  <input type="text" value={activeSearch} onChange={(e) => setActiveSearch(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); loadRules(); } }}
                    placeholder="Search rules…" className="safety-input" />
                </div>
                <button onClick={handleClearFilters} className="safety-clear-btn">Clear</button>
              </div>
            </div>

            {/* PDF Document Cards — BELOW filters */}
            {docCards.length > 0 && (
              <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                {docCards.map((doc) => (
                  <button key={doc.name} onClick={() => handleDocClick(doc.name)}
                    className={`glass-card px-4 py-3 text-left transition-all cursor-pointer hover:border-accent/40 ${expandedDoc === doc.name ? 'ring-1 ring-accent border-accent/50' : ''}`}>
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: 'rgba(99,102,241,0.15)' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                        </svg>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">{doc.name}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-muted">{doc.rule_count} rules</span>
                          <span className="text-xs px-1.5 py-0.5 rounded"
                            style={{
                              backgroundColor: `${SEV_COLORS[Math.round(doc.avg_severity)] ?? SEV_COLORS[3]}20`,
                              color: SEV_COLORS[Math.round(doc.avg_severity)] ?? SEV_COLORS[3]
                            }}>
                            Avg: {doc.avg_severity}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {doc.categories.slice(0, 3).map((cat) => <span key={cat} className="safety-category-pill">{cat}</span>)}
                          {doc.categories.length > 3 && <span className="text-xs text-muted">+{doc.categories.length - 3}</span>}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Collapsible Rules Section */}
            <div className="glass-card overflow-hidden">
              <button onClick={() => setRulesExpanded(!rulesExpanded)}
                className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-medium text-foreground">Rules Table</h3>
                  {dbRules && !dbLoading && (
                    <span className="text-xs text-muted">
                      {dbRules.total} rules
                      {expandedDoc && <> · Filtered by <strong className="text-foreground">{expandedDoc}</strong></>}
                      {activeRunId != null && <> · Run #{activeRunId}</>}
                      {totalPages > 1 && ` · Page ${page}/${totalPages}`}
                    </span>
                  )}
                </div>
                <Chevron open={rulesExpanded} />
              </button>

              {rulesExpanded && (
                <div className="border-t border-card-border">
                  {/* Loading */}
                  {dbLoading && (
                    <div className="px-6 py-6">
                      <div className="summary-loading">
                        <p className="summary-loading-text">Loading rules…</p>
                        <div className="summary-skeleton"><div className="summary-skeleton-line" /><div className="summary-skeleton-line" /></div>
                      </div>
                    </div>
                  )}

                  {dbError && (
                    <div className="px-6 py-4"><p className="text-sm" style={{ color: 'var(--color-unsafe)' }}>{dbError}</p></div>
                  )}

                  {/* Table */}
                  {!dbLoading && dbRules && dbRules.rules.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="safety-table">
                        <thead>
                          <tr>
                            <th>#</th><th>Actionable Rule</th><th>Original Text</th><th>Materials</th>
                            <th>Categories</th><th>Severity</th><th>Page</th><th>Heading</th><th>Source</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dbRules.rules.map((rule, idx) => (
                            <tr key={rule.rule_id}>
                              <td className="text-muted text-xs">{(page - 1) * PER_PAGE + idx + 1}</td>
                              <td className="max-w-[350px]">{rule.actionable_rule}</td>
                              <td className="max-w-[250px] text-muted text-xs"><div className="line-clamp-3">{rule.original_text}</div></td>
                              <td className="text-xs text-muted max-w-[150px]">{rule.materials?.length ? rule.materials.join(', ') : '—'}</td>
                              <td><div className="flex flex-wrap gap-1">{rule.categories.map((cat) => <span key={cat} className="safety-category-pill">{cat}</span>)}</div></td>
                              <td><span className={`safety-severity-badge severity-${rule.validated_severity ?? 1}`}>{rule.validated_severity ?? '?'}</span></td>
                              <td className="text-xs text-muted">{rule.page_number ?? '—'}</td>
                              <td className="text-xs text-muted max-w-[120px] truncate" title={rule.section_heading}>{rule.section_heading}</td>
                              <td className="text-xs text-muted whitespace-nowrap">{rule.source_document}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {!dbLoading && dbRules && dbRules.rules.length === 0 && !dbError && (
                    <div className="px-6 py-8 text-center"><p className="text-muted text-sm">No rules found matching your filters.</p></div>
                  )}

                  {/* Pagination */}
                  {!dbLoading && totalPages > 1 && (
                    <div className="flex justify-center items-center gap-2 py-4 border-t border-card-border">
                      <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="safety-page-btn">← Prev</button>
                      {Array.from({ length: totalPages }, (_, i) => i + 1)
                        .filter((p) => p <= 3 || p > totalPages - 3 || (p >= page - 2 && p <= page + 2))
                        .map((p, i, arr) => {
                          const showEllipsis = i > 0 && p - arr[i - 1] > 1;
                          return (
                            <span key={p}>
                              {showEllipsis && <span className="text-muted px-1">…</span>}
                              <button onClick={() => setPage(p)} className={`safety-page-btn ${p === page ? 'active' : ''}`}>{p}</button>
                            </span>
                          );
                        })}
                      <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="safety-page-btn">Next →</button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {/* ════════════ ALL RUNS VIEW ════════════ */}
        {viewMode === 'runs' && (
          <>
            {runsLoading && (
              <div className="glass-card px-6 py-8">
                <div className="summary-loading">
                  <p className="summary-loading-text">Loading extraction runs…</p>
                  <div className="summary-skeleton"><div className="summary-skeleton-line" /><div className="summary-skeleton-line" /></div>
                </div>
              </div>
            )}

            {!runsLoading && runs.length === 0 && (
              <div className="glass-card px-6 py-12 text-center">
                <p className="text-muted text-sm">No extraction runs yet. Upload PDFs to create a run.</p>
              </div>
            )}

            {!runsLoading && runs.map((run) => {
              const isExpanded = expandedRun === run.id;

              // Only show docs from this run's json_source_file (not all source_documents)
              const runFileName = run.json_source_file || '';
              const runDocs = runFileName ? [runFileName] : (run.source_documents || []);

              return (
                <div key={run.id} className="glass-card overflow-hidden">
                  {/* Run header — collapsible */}
                  <button onClick={() => handleExpandRun(run.id)}
                    className="w-full px-5 py-4 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer">
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-lg flex items-center justify-center font-bold text-sm"
                        style={{ backgroundColor: 'rgba(99,102,241,0.15)', color: 'var(--color-accent)' }}>
                        #{run.id}
                      </div>
                      <div className="text-left">
                        <p className="text-sm font-medium text-foreground">
                          Run #{run.id} — {runDocs.join(', ') || 'Extraction Run'}
                        </p>
                        <div className="flex items-center gap-3 mt-0.5 text-xs text-muted">
                          <span>{new Date(run.run_timestamp).toLocaleDateString()}</span>
                          <span>·</span>
                          <span>{run.rule_count} rules</span>
                          <span>·</span>
                          <span>{run.total_pages} pages</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {run.evaluation_results && <EvalBadge ev={run.evaluation_results} />}
                      {!run.evaluation_results && (
                        <span className="text-xs text-muted px-2 py-1 rounded-md"
                          style={{ backgroundColor: 'rgba(156,163,175,0.15)' }}>No eval</span>
                      )}
                      <Chevron open={isExpanded} />
                    </div>
                  </button>

                  {/* Expanded run content */}
                  {isExpanded && (
                    <div className="border-t border-card-border">

                      {/* ── Metadata dropdown ── */}
                      <RunMetaSection run={run} />

                      {/* ── Evaluation section ── */}
                      {run.evaluation_results ? (
                        <EvalDetails ev={run.evaluation_results} />
                      ) : (
                        <div className="px-5 py-4 flex items-center gap-3" style={{ backgroundColor: 'rgba(0,0,0,0.05)' }}>
                          <span className="text-xs text-muted">No evaluation results for this run.</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleRunEvaluation(run.id); }}
                            disabled={evaluatingRunId === run.id}
                            className="summary-action-btn text-xs"
                          >
                            {evaluatingRunId === run.id ? (
                              <><svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg> Evaluating…</>
                            ) : (
                              '▶ Run Evaluation'
                            )}
                          </button>
                        </div>
                      )}

                      {/* ── Rules dropdown inside run ── */}
                      <div className="border-t border-card-border">
                        <button onClick={() => setRunRulesExpanded(!runRulesExpanded)}
                          className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer">
                          <span className="text-xs font-medium text-muted uppercase tracking-wider">
                            Rules from this run ({runRules?.total ?? '…'})
                          </span>
                          <Chevron open={runRulesExpanded} />
                        </button>

                        {runRulesExpanded && (
                          <div className="border-t border-card-border">
                            {runRulesLoading && <div className="px-5 py-4"><p className="text-sm text-muted">Loading rules…</p></div>}

                            {!runRulesLoading && runRules && runRules.rules.length > 0 && (
                              <div className="overflow-x-auto">
                                <table className="safety-table">
                                  <thead>
                                    <tr><th>#</th><th>Actionable Rule</th><th>Original Text</th><th>Materials</th>
                                      <th>Categories</th><th>Severity</th><th>Page</th><th>Heading</th><th>Source</th></tr>
                                  </thead>
                                  <tbody>
                                    {runRules.rules.slice(0, 50).map((rule, idx) => (
                                      <tr key={rule.rule_id}>
                                        <td className="text-muted text-xs">{idx + 1}</td>
                                        <td className="max-w-[350px]">{rule.actionable_rule}</td>
                                        <td className="max-w-[250px] text-muted text-xs"><div className="line-clamp-2">{rule.original_text}</div></td>
                                        <td className="text-xs text-muted max-w-[150px]">{rule.materials?.length ? rule.materials.join(', ') : '—'}</td>
                                        <td><div className="flex flex-wrap gap-1">{rule.categories.map((cat) => <span key={cat} className="safety-category-pill">{cat}</span>)}</div></td>
                                        <td><span className={`safety-severity-badge severity-${rule.validated_severity ?? 1}`}>{rule.validated_severity ?? '?'}</span></td>
                                        <td className="text-xs text-muted">{rule.page_number ?? '—'}</td>
                                        <td className="text-xs text-muted max-w-[120px] truncate">{rule.section_heading}</td>
                                        <td className="text-xs text-muted whitespace-nowrap">{rule.source_document}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                                {runRules.total > 50 && (
                                  <p className="text-xs text-muted px-5 py-2">Showing 50 of {runRules.total} rules</p>
                                )}
                              </div>
                            )}

                            {!runRulesLoading && runRules && runRules.rules.length === 0 && (
                              <div className="px-5 py-6 text-center"><p className="text-sm text-muted">No rules found for this run.</p></div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </>
        )}
      </main>
    </div>
  );
}


/* ─────── Run Metadata collapsible ─────── */

function RunMetaSection({ run }: { run: ExtractionRun }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-card-border">
      <button onClick={() => setOpen(!open)}
        className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer">
        <span className="text-xs font-medium text-muted uppercase tracking-wider">Run Metadata</span>
        <Chevron open={open} />
      </button>
      {open && (
        <div className="px-5 py-3 space-y-0.5" style={{ backgroundColor: 'rgba(0,0,0,0.05)' }}>
          <MetaRow label="Run ID" value={`#${run.id}`} mono />
          <MetaRow label="Timestamp" value={new Date(run.run_timestamp).toLocaleString()} />
          <MetaRow label="Model Used" value={run.model_used} mono />
          <MetaRow label="Total Pages" value={String(run.total_pages)} />
          <MetaRow label="Rule Count" value={String(run.rule_count)} />
          <MetaRow label="Document Count" value={String(run.document_count)} />
          {run.source_documents && run.source_documents.length > 0 && (
            <MetaRow label="Source Documents" value={run.source_documents.join(', ')} />
          )}
          <MetaRow label="JSON Source File" value={run.json_source_file || '—'} mono />
          {run.file_url && <MetaRow label="Storage URL" value={run.file_url} mono />}
          <MetaRow label="Created At" value={new Date(run.created_at).toLocaleString()} />
          <MetaRow label="Has Evaluation" value={run.evaluation_results ? '✓ Yes' : '✗ No'} />
        </div>
      )}
    </div>
  );
}

function MetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-4 py-1.5">
      <span className="text-xs text-muted w-36 flex-shrink-0">{label}</span>
      <span className={`text-xs text-foreground break-all ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  );
}


/* ─────── Evaluation sub-components ─────── */

const CHECK_DESCRIPTIONS: Record<string, string> = {
  text_presence: 'Verifies extracted original_text exists in the actual PDF content',
  page_accuracy: 'Checks if the rule appears on the claimed page (±1 tolerance)',
  heading_accuracy: 'Confirms section_heading matches an actual heading on that page',
  rule_structure: 'Validates actionable_rule starts with an imperative verb (ensure, use, wear...)',
  category_validity: 'Checks all categories are from the 12 allowed categories list',
  severity_consistency: 'Ensures validated_severity ≥ suggested and hazardous content gets ≥3',
};

function EvalBadge({ ev }: { ev: EvaluationResults }) {
  const acc = ev.overall_accuracy;
  const bg = acc >= 90 ? 'rgba(34,197,94,0.15)' : acc >= 70 ? 'rgba(234,179,8,0.15)' : 'rgba(239,68,68,0.15)';
  const color = acc >= 90 ? 'var(--color-safe)' : acc >= 70 ? 'var(--color-caution)' : 'var(--color-unsafe)';
  return (
    <span className="text-xs font-semibold px-2 py-1 rounded-md" style={{ backgroundColor: bg, color }}>
      {acc}% accurate
    </span>
  );
}

function EvalDetails({ ev }: { ev: EvaluationResults }) {
  const [open, setOpen] = useState(false);
  const checksPerformed = Object.keys(ev.per_check_accuracy);
  const totalChecks = ev.total_checks;
  const totalPassed = ev.checks_passed;

  return (
    <div>
      <button onClick={() => setOpen(!open)}
        className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer border-b border-card-border">
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-muted uppercase tracking-wider">Evaluation Results</span>
          <EvalBadge ev={ev} />
        </div>
        <Chevron open={open} />
      </button>
      {open && (
        <div className="px-5 py-4 space-y-4" style={{ backgroundColor: 'rgba(0,0,0,0.05)' }}>

          {/* Summary stats */}
          <div className="flex flex-wrap gap-4 text-xs">
            <div className="glass-card px-3 py-2 rounded-lg border border-card-border">
              <span className="text-muted">Rules Evaluated</span>
              <p className="text-foreground font-semibold text-sm mt-0.5">{ev.total_rules}</p>
            </div>
            <div className="glass-card px-3 py-2 rounded-lg border border-card-border">
              <span className="text-muted">Tests Run</span>
              <p className="text-foreground font-semibold text-sm mt-0.5">{checksPerformed.length} checks × {ev.total_rules} rules = {totalChecks}</p>
            </div>
            <div className="glass-card px-3 py-2 rounded-lg border border-card-border">
              <span className="text-muted">Checks Passed</span>
              <p className="font-semibold text-sm mt-0.5" style={{ color: 'var(--color-safe)' }}>{totalPassed} / {totalChecks}</p>
            </div>
            <div className="glass-card px-3 py-2 rounded-lg border border-card-border">
              <span className="text-muted">Rules with Issues</span>
              <p className="font-semibold text-sm mt-0.5" style={{ color: ev.rules_with_failures > 0 ? 'var(--color-caution)' : 'var(--color-safe)' }}>
                {ev.rules_with_failures} / {ev.total_rules}
              </p>
            </div>
          </div>

          {/* Accuracy formula */}
          <div className="text-xs px-3 py-2 rounded-lg border border-card-border" style={{ backgroundColor: 'rgba(99,102,241,0.05)' }}>
            <p className="text-muted mb-1 font-medium">📐 Overall Accuracy Formula:</p>
            <p className="font-mono text-foreground">
              accuracy = (checks_passed / total_checks) × 100
              = ({totalPassed} / {totalChecks}) × 100
              = <strong>{ev.overall_accuracy}%</strong>
            </p>
          </div>

          {/* Per-check breakdown */}
          <div>
            <p className="text-xs font-medium text-muted uppercase tracking-wider mb-2">Individual Test Scores</p>
            <div className="space-y-3">
              {checksPerformed.map((check) => {
                const pct = ev.per_check_accuracy[check] ?? 0;
                const barColor = pct >= 90 ? 'var(--color-safe)' : pct >= 70 ? 'var(--color-caution)' : 'var(--color-unsafe)';
                const passed = Math.round((pct / 100) * ev.total_rules);
                const failed = ev.total_rules - passed;
                return (
                  <div key={check} className="px-3 py-2 rounded-lg border border-card-border">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-foreground">{CHECK_LABELS[check] || check}</span>
                      <span className="text-xs font-mono font-bold" style={{ color: barColor }}>{pct}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-input-bg overflow-hidden mb-1.5">
                      <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                    </div>
                    <div className="flex justify-between text-xs text-muted">
                      <span>{CHECK_DESCRIPTIONS[check] || 'Custom evaluation check'}</span>
                      <span className="flex-shrink-0 ml-2">
                        <span style={{ color: 'var(--color-safe)' }}>{passed} passed</span>
                        {failed > 0 && <span style={{ color: 'var(--color-unsafe)' }}> · {failed} failed</span>}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Failed rules detail */}
          {ev.failed_rules.length > 0 && (
            <details className="text-xs">
              <summary className="text-muted cursor-pointer hover:text-foreground transition-colors font-medium">
                ▸ View {ev.failed_rules.length} rules with issues
              </summary>
              <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                {ev.failed_rules.slice(0, 15).map((fr) => (
                  <div key={fr.rule_id} className="flex items-start gap-2 px-2 py-1.5 rounded border border-card-border" style={{ backgroundColor: 'rgba(239,68,68,0.04)' }}>
                    <span className="text-muted truncate flex-1">{fr.actionable_rule}</span>
                    <span className="flex-shrink-0" style={{ color: 'var(--color-unsafe)' }}>
                      Failed: {fr.failed_checks.map((c) => CHECK_LABELS[c] || c).join(', ')}
                    </span>
                  </div>
                ))}
                {ev.failed_rules.length > 15 && <p className="text-muted px-2">…and {ev.failed_rules.length - 15} more</p>}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/* ─────── Extraction Progress Panel ─────── */

const PIPELINE_STEPS: Array<{ key: ExtractionStep; label: string }> = [
  { key: 'upload', label: 'Upload' },
  { key: 'ingestion', label: 'Read' },
  { key: 'llm_extraction', label: 'Extract' },
  { key: 'validation', label: 'Validate' },
  { key: 'db_insert', label: 'Save' },
  { key: 'complete', label: 'Done' },
];

// Map alias steps to their nearest display step
function resolveStepIdx(step: ExtractionStep | null): number {
  if (!step) return -1;
  const direct = PIPELINE_STEPS.findIndex((s) => s.key === step);
  if (direct >= 0) return direct;
  // Map intermediates
  if (step === 'severity' || step === 'embedding' || step === 'dedup') return 3; // validation
  if (step === 'evaluation') return 4; // db_insert phase
  if (step === 'done' || step === 'complete') return PIPELINE_STEPS.length - 1;
  return -1;
}

function ExtractionProgress({
  events, currentStep, extracting, error, onDismiss,
}: {
  events: ExtractionProgressEvent[];
  currentStep: ExtractionStep | null;
  extracting: boolean;
  error: string | null;
  onDismiss: () => void;
}) {
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events.length]);

  const lastEvent = events[events.length - 1];
  const isComplete = currentStep === 'done' || currentStep === 'complete';
  const hasError = currentStep === 'error' || !!error;
  const activeIdx = resolveStepIdx(currentStep);

  return (
    <div className="analysis-progress glass-card animate-fade-in">
      {/* Phase stepper — mirrors AnalysisProgress */}
      <div className="progress-stepper">
        {PIPELINE_STEPS.map((p, i) => {
          const isDone = i < activeIdx || isComplete;
          const isActive = i === activeIdx && !isComplete;
          const stateClass = hasError && isActive
            ? 'progress-step-error'
            : isDone
              ? 'progress-step-done'
              : isActive
                ? 'progress-step-active'
                : 'progress-step-pending';

          return (
            <div key={p.key} className="progress-step-wrapper">
              {i > 0 && (
                <div className={`progress-connector ${isDone ? 'progress-connector-done' : ''}`} />
              )}
              <div className={`progress-step ${stateClass}`}>
                <span className="progress-step-icon">{isDone ? '✓' : (i + 1)}</span>
              </div>
              <span className={`progress-step-label ${isActive ? 'text-foreground' : 'text-muted'}`}>
                {p.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Status text + dismiss */}
      <div className="progress-footer" style={{ position: 'relative' }}>
        <p className="progress-status">
          {hasError
            ? '✗ Extraction failed'
            : isComplete
              ? '✓ Extraction complete'
              : lastEvent?.status ?? 'Preparing…'}
        </p>
        {!extracting && (
          <button
            onClick={onDismiss}
            className="text-muted hover:text-foreground text-xs"
            style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)' }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Error display */}
      {error && (
        <div className="px-5 pb-2">
          <p className="text-xs font-medium" style={{ color: 'var(--color-unsafe)' }}>
            {error.length > 200 ? error.slice(0, 200) + '…' : error}
          </p>
        </div>
      )}

      {/* Event log (collapsible) */}
      {events.length > 2 && (
        <details className="border-t border-card-border">
          <summary className="px-5 py-2 text-xs text-muted cursor-pointer hover:text-foreground transition-colors">
            ▸ View extraction log ({events.length} events)
          </summary>
          <div
            ref={logRef}
            className="max-h-40 overflow-y-auto px-5 pb-2 space-y-0.5"
            style={{ backgroundColor: 'rgba(0,0,0,0.05)' }}
          >
            {events.map((evt, i) => (
              <div key={i} className="flex items-start gap-2 text-xs py-0.5">
                <span className="text-muted flex-shrink-0 w-24 font-mono">
                  {evt.step}
                </span>
                <span className={evt.step === 'error' ? 'text-red-400' : 'text-foreground'}>
                  {evt.status}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
