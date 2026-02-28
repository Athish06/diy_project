import { useState, useMemo } from 'react';
import type { SafetyRule } from '@/types/safety';
import { SEVERITY_MAP } from '@/types/safety';

interface SafetyRulesTableProps {
  rules: SafetyRule[];
  documentName: string;
}

export default function SafetyRulesTable({ rules, documentName }: SafetyRulesTableProps) {
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [minSeverity, setMinSeverity] = useState<number>(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const categories = useMemo(() => {
    const cats = new Set(rules.map((r) => r.category));
    return Array.from(cats).sort();
  }, [rules]);

  const filtered = useMemo(() => {
    return rules.filter((r) => {
      if (categoryFilter !== 'all' && r.category !== categoryFilter) return false;
      if (r.severity < minSeverity) return false;
      return true;
    });
  }, [rules, categoryFilter, minSeverity]);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted font-medium uppercase tracking-wider">
            Category
          </label>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="safety-select"
          >
            <option value="all">All Categories</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted font-medium uppercase tracking-wider">
            Min Severity
          </label>
          <select
            value={minSeverity}
            onChange={(e) => setMinSeverity(Number(e.target.value))}
            className="safety-select"
          >
            {[1, 2, 3, 4, 5].map((s) => (
              <option key={s} value={s}>
                {s} – {SEVERITY_MAP[s].label}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto text-sm text-muted self-end pb-1">
          {filtered.length} / {rules.length} rules
        </div>
      </div>

      {/* Rules list */}
      {filtered.length === 0 ? (
        <div className="glass-card px-6 py-8 text-center">
          <p className="text-muted text-sm">No rules match the current filters.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((rule, idx) => {
            const sev = SEVERITY_MAP[rule.severity] ?? SEVERITY_MAP[3];
            const isExpanded = expandedId === rule.id;

            return (
              <div
                key={rule.id}
                className="glass-card overflow-hidden transition-all duration-200"
                style={{ animationDelay: `${idx * 30}ms` }}
              >
                <button
                  onClick={() => setExpandedId(isExpanded ? null : rule.id)}
                  className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-input-bg transition-colors"
                >
                  <span
                    className={`safety-severity-badge ${sev.bgClass}`}
                    title={`Severity ${rule.severity}: ${sev.label}`}
                  >
                    {rule.severity}
                  </span>
                  <span className="flex-1 text-sm leading-relaxed">
                    {rule.rule_text}
                  </span>
                  <span className="safety-category-pill shrink-0">
                    {rule.category}
                  </span>
                  <svg
                    className={`w-4 h-4 text-muted shrink-0 mt-0.5 transition-transform ${
                      isExpanded ? 'rotate-180' : ''
                    }`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {isExpanded && (
                  <div className="px-4 pb-4 pt-1 border-t border-card-border space-y-2 text-sm animate-fade-in">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                      <div>
                        <span className="text-muted">Source:</span>{' '}
                        <span>{rule.source_document}</span>
                      </div>
                      <div>
                        <span className="text-muted">Page:</span>{' '}
                        <span>{rule.page_number}</span>
                      </div>
                      <div>
                        <span className="text-muted">Section:</span>{' '}
                        <span>{rule.section_heading || '—'}</span>
                      </div>
                      <div>
                        <span className="text-muted">Actionable:</span>{' '}
                        <span>{rule.actionable ? 'Yes' : 'No'}</span>
                      </div>
                    </div>

                    {rule.applies_to && rule.applies_to.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        <span className="text-xs text-muted">Applies to:</span>
                        {rule.applies_to.map((t) => (
                          <span key={t} className="safety-applies-pill">{t}</span>
                        ))}
                      </div>
                    )}

                    {rule.source_quote && (
                      <blockquote className="mt-2 text-xs text-muted italic border-l-2 border-card-border pl-3 leading-relaxed">
                        &ldquo;{rule.source_quote}&rdquo;
                      </blockquote>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
