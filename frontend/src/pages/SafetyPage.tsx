import { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { Link } from 'react-router-dom';
import { extractRules, fetchRules, fetchFilterOptions } from '@/lib/api';
import { useTheme } from '@/contexts/ThemeContext';
import type { SafetyExtractionResult, DbRulesResponse, FilterOptions } from '@/types/safety';

const SafetyRulesTable = lazy(() => import('@/components/SafetyRulesTable'));

type ViewMode = 'db' | 'extraction';

export default function SafetyPage() {
  // --- DB rules state ---
  const [dbRules, setDbRules] = useState<DbRulesResponse | null>(null);
  const [filters, setFilters] = useState<FilterOptions | null>(null);
  const [activeCategory, setActiveCategory] = useState('');
  const [activeSeverity, setActiveSeverity] = useState('');
  const [activeDocument, setActiveDocument] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [page, setPage] = useState(1);
  const [dbLoading, setDbLoading] = useState(true);
  const [dbError, setDbError] = useState<string | null>(null);

  // --- Extraction state ---
  const [extractionResult, setExtractionResult] = useState<SafetyExtractionResult | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  // --- View mode ---
  const [viewMode, setViewMode] = useState<ViewMode>('db');

  // Hidden file input ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  const PER_PAGE = 50;

  // Load filter options on mount
  useEffect(() => {
    fetchFilterOptions()
      .then(setFilters)
      .catch((e) => console.error('Failed to load filters:', e));
  }, []);

  // Fetch rules whenever filters or page change
  const loadRules = useCallback(async () => {
    setDbLoading(true);
    setDbError(null);
    try {
      const data = await fetchRules({
        category: activeCategory || undefined,
        severity: activeSeverity ? Number(activeSeverity) : undefined,
        document: activeDocument || undefined,
        search: activeSearch || undefined,
        page,
        perPage: PER_PAGE,
      });
      setDbRules(data);
    } catch (err) {
      setDbError(err instanceof Error ? err.message : String(err));
    } finally {
      setDbLoading(false);
    }
  }, [activeCategory, activeSeverity, activeDocument, activeSearch, page]);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  const handleClearFilters = useCallback(() => {
    setActiveCategory('');
    setActiveSeverity('');
    setActiveDocument('');
    setActiveSearch('');
    setPage(1);
  }, []);

  // --- Extraction handlers ---
  const handleUploadClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileSelected = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset file input so same file can be selected again
    e.target.value = '';

    setFileName(file.name);
    setExtracting(true);
    setExtractionResult(null);
    setExtractError(null);
    setViewMode('extraction');

    try {
      const data = await extractRules(file);
      setExtractionResult(data);
      // Refresh DB rules & filters after extraction
      loadRules();
      fetchFilterOptions().then(setFilters).catch(() => { });
    } catch (err) {
      setExtractError(err instanceof Error ? err.message : String(err));
    } finally {
      setExtracting(false);
    }
  }, [loadRules]);

  const handleDownload = useCallback(() => {
    if (!extractionResult) return;
    const blob = new Blob([JSON.stringify(extractionResult, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${extractionResult.document_name}_rules.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [extractionResult]);

  const totalPages = dbRules ? Math.max(1, Math.ceil(dbRules.total / PER_PAGE)) : 1;

  const { theme, toggleTheme } = useTheme();

  return (
    <div className="safety-page-shell">

      {/* Hidden file input for PDF upload */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleFileSelected}
      />

      {/* Header */}
      <header className="safety-page-header">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to="/"
              className="text-muted hover:text-foreground transition-colors"
              aria-label="Back to Analyzer"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5" />
                <path d="M12 19l-7-7 7-7" />
              </svg>
            </Link>
            <div>
              <h1 className="text-xl font-bold text-foreground">Safety Rules</h1>
              <p className="text-xs text-muted mt-0.5">
                Browse extracted rules or ingest new PDF rulebooks
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              className="topbar-theme-toggle"
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === 'dark' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="5" />
                  <line x1="12" y1="1" x2="12" y2="3" />
                  <line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" />
                  <line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              )}
            </button>

            {/* Upload button */}
            <button
              onClick={handleUploadClick}
              disabled={extracting}
              className="safety-upload-btn"
            >
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
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  Ingest PDF
                </>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1 px-6 pb-6 space-y-4">
        {/* View mode tabs */}
        <div className="flex gap-1 p-1 bg-input-bg rounded-lg w-fit">
          <button
            onClick={() => setViewMode('db')}
            className={`px-4 py-1.5 text-sm rounded-md transition-all ${viewMode === 'db'
                ? 'bg-card-bg text-foreground font-medium shadow-sm border border-card-border'
                : 'text-muted hover:text-foreground'
              }`}
          >
            All Rules
            {dbRules && <span className="ml-1.5 text-xs opacity-60">({dbRules.total})</span>}
          </button>
          <button
            onClick={() => setViewMode('extraction')}
            className={`px-4 py-1.5 text-sm rounded-md transition-all ${viewMode === 'extraction'
                ? 'bg-card-bg text-foreground font-medium shadow-sm border border-card-border'
                : 'text-muted hover:text-foreground'
              }`}
          >
            Latest Extraction
            {extractionResult && (
              <span className="ml-1.5 text-xs opacity-60">({extractionResult.rule_count})</span>
            )}
          </button>
        </div>

        {/* ===== DB VIEW ===== */}
        {viewMode === 'db' && (
          <>
            {/* Filters bar */}
            <div className="glass-card px-5 py-4">
              <div className="flex flex-wrap gap-3 items-end">
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Category</label>
                  <select value={activeCategory} onChange={(e) => { setActiveCategory(e.target.value); setPage(1); }} className="safety-select">
                    <option value="">All Categories</option>
                    {filters?.categories.map((cat) => (
                      <option key={cat} value={cat}>{cat}</option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Severity</label>
                  <select value={activeSeverity} onChange={(e) => { setActiveSeverity(e.target.value); setPage(1); }} className="safety-select">
                    <option value="">All Severities</option>
                    {filters?.severities.map((sev) => (
                      <option key={sev} value={sev}>
                        {sev} — {({ 5: 'Critical', 4: 'High', 3: 'Medium', 2: 'Low', 1: 'Info' } as Record<number, string>)[sev] ?? sev}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Document</label>
                  <select value={activeDocument} onChange={(e) => { setActiveDocument(e.target.value); setPage(1); }} className="safety-select">
                    <option value="">All Documents</option>
                    {filters?.documents.map((doc) => (
                      <option key={doc} value={doc}>{doc}</option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted font-medium uppercase tracking-wider">Search</label>
                  <input
                    type="text"
                    value={activeSearch}
                    onChange={(e) => setActiveSearch(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); loadRules(); } }}
                    placeholder="Search rules…"
                    className="safety-input"
                  />
                </div>

                <button onClick={handleClearFilters} className="safety-clear-btn">Clear</button>
              </div>
            </div>

            {/* Summary bar */}
            {dbRules && !dbLoading && (
              <div className="flex justify-between items-center text-sm text-muted px-1">
                <span>
                  Showing {dbRules.rules.length} of {dbRules.total} rules
                  {totalPages > 1 && ` (page ${page} of ${totalPages})`}
                </span>
              </div>
            )}

            {/* Loading */}
            {dbLoading && (
              <div className="glass-card px-6 py-8">
                <div className="summary-loading">
                  <p className="summary-loading-text">Loading rules from database…</p>
                  <div className="summary-skeleton">
                    <div className="summary-skeleton-line" />
                    <div className="summary-skeleton-line" />
                    <div className="summary-skeleton-line" />
                  </div>
                </div>
              </div>
            )}

            {/* Error */}
            {dbError && (
              <div className="glass-card px-6 py-4 border-red-500/30 bg-red-500/5">
                <p className="text-sm text-red-500">{dbError}</p>
              </div>
            )}

            {/* Rules table */}
            {!dbLoading && dbRules && dbRules.rules.length > 0 && (
              <div className="glass-card overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="safety-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Actionable Rule</th>
                        <th>Original Text</th>
                        <th>Severity</th>
                        <th>Categories</th>
                        <th>Materials</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dbRules.rules.map((rule, idx) => (
                        <tr key={rule.rule_id}>
                          <td className="text-muted text-xs">{(page - 1) * PER_PAGE + idx + 1}</td>
                          <td className="max-w-[400px]">{rule.actionable_rule}</td>
                          <td className="max-w-[300px] text-muted text-xs">
                            <div className="line-clamp-3">{rule.original_text}</div>
                          </td>
                          <td>
                            <span className={`safety-severity-badge severity-${rule.validated_severity ?? 1}`}>
                              {rule.validated_severity ?? '?'}
                            </span>
                          </td>
                          <td>
                            <div className="flex flex-wrap gap-1">
                              {rule.categories.map((cat) => (
                                <span key={cat} className="safety-category-pill">
                                  {cat}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="text-xs text-muted max-w-[200px]">
                            {rule.materials?.length ? rule.materials.join(', ') : ''}
                          </td>
                          <td className="text-xs text-muted whitespace-nowrap">
                            {rule.source_document}
                            <br />
                            <small>p.{rule.page_number} · {rule.section_heading}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Empty state */}
            {!dbLoading && dbRules && dbRules.rules.length === 0 && !dbError && (
              <div className="glass-card px-6 py-12 text-center">
                <p className="text-muted text-sm">No rules found matching your filters.</p>
              </div>
            )}

            {/* Pagination */}
            {!dbLoading && totalPages > 1 && (
              <div className="flex justify-center items-center gap-2 py-4">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="safety-page-btn"
                >
                  ← Prev
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter((p) => p <= 3 || p > totalPages - 3 || (p >= page - 2 && p <= page + 2))
                  .map((p, i, arr) => {
                    const showEllipsis = i > 0 && p - arr[i - 1] > 1;
                    return (
                      <span key={p}>
                        {showEllipsis && <span className="text-muted px-1">…</span>}
                        <button
                          onClick={() => setPage(p)}
                          className={`safety-page-btn ${p === page ? 'active' : ''}`}
                        >
                          {p}
                        </button>
                      </span>
                    );
                  })}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="safety-page-btn"
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}

        {/* ===== EXTRACTION VIEW ===== */}
        {viewMode === 'extraction' && (
          <Suspense fallback={null}>
            <>
              {/* Extracting state */}
              {extracting && (
                <div className="glass-card px-6 py-8">
                  <div className="summary-loading">
                    <p className="summary-loading-text">
                      Extracting safety rules from {fileName}… This may take a minute.
                    </p>
                    <div className="summary-skeleton">
                      <div className="summary-skeleton-line" />
                      <div className="summary-skeleton-line" />
                      <div className="summary-skeleton-line" />
                      <div className="summary-skeleton-line" />
                    </div>
                  </div>
                </div>
              )}

              {/* Extraction error */}
              {extractError && (
                <div className="glass-card px-6 py-4 border-red-500/30 bg-red-500/5">
                  <p className="text-sm text-red-500">{extractError}</p>
                </div>
              )}

              {/* Extraction results */}
              {extractionResult && !extracting && (
                <>
                  {/* Stats bar */}
                  <div className="glass-card px-5 py-3 flex flex-wrap gap-x-6 gap-y-1 text-sm items-center">
                    <div>
                      <span className="text-muted">File:</span>{' '}
                      <span className="font-medium">{fileName}</span>
                    </div>
                    <div>
                      <span className="text-muted">Rules:</span>{' '}
                      <span className="font-semibold">{extractionResult.rule_count}</span>
                    </div>
                    <div>
                      <span className="text-muted">Pages:</span>{' '}
                      <span className="font-semibold">{extractionResult.total_pages}</span>
                    </div>
                    <div>
                      <span className="text-muted">Model:</span>{' '}
                      <span className="font-mono text-xs">{extractionResult.model_used}</span>
                    </div>
                    <button onClick={handleDownload} className="summary-action-btn ml-auto">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      Download JSON
                    </button>
                  </div>

                  <SafetyRulesTable
                    rules={extractionResult.rules}
                    documentName={extractionResult.document_name}
                  />
                </>
              )}

              {/* Empty extraction state */}
              {!extractionResult && !extracting && !extractError && (
                <div className="glass-card px-6 py-12 text-center space-y-3">
                  <div className="flex justify-center">
                    <svg className="w-12 h-12 text-muted opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
                    </svg>
                  </div>
                  <p className="text-muted text-sm">
                    Click &ldquo;Ingest PDF&rdquo; to extract rules from a new rulebook.
                  </p>
                  <p className="text-muted text-xs opacity-60">
                    Rules will appear here after extraction completes.
                  </p>
                </div>
              )}
            </>
          </Suspense>
        )}
      </main>

    </div>
  );
}
