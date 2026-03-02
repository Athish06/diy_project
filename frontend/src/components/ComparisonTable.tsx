import { memo } from 'react';
import type { ModelComparison } from '@/types';

interface ComparisonTableProps {
  comparison: ModelComparison;
  modelColors: Record<string, string>;
}

function getVerdictColor(val: string | number): string {
  const v = String(val);
  if (v === 'SAFE') return '#6ee7b7';
  if (v === 'UNSAFE') return '#f87171';
  if (v === 'PROFESSIONAL_REQUIRED') return '#fb923c';
  return '';
}

function formatValue(val: string | number): string {
  if (typeof val === 'number') return String(val);
  if (val === 'PROFESSIONAL_REQUIRED') return 'Professional Required';
  return String(val);
}

const ComparisonTable = memo(function ComparisonTable({ comparison, modelColors }: ComparisonTableProps) {
  if (!comparison || comparison.aspects.length === 0) return null;

  const models = comparison.models;

  return (
    <div className="comparison-table-wrapper glass-card animate-fade-in">
      <div className="comparison-header">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" />
          <rect x="14" y="3" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" />
        </svg>
        <h3 className="comparison-title">Model Comparison</h3>
      </div>

      <div className="comparison-table-scroll">
        <table className="comparison-table">
          <thead>
            <tr>
              <th className="ct-aspect-header">Aspect</th>
              {models.map((m) => (
                <th key={m.key} className="ct-model-header">
                  <span className="ct-model-dot" style={{ background: modelColors[m.key] || '#a78bfa' }} />
                  {m.label}
                </th>
              ))}
              <th className="ct-agree-header">Agreement</th>
            </tr>
          </thead>
          <tbody>
            {comparison.aspects.map((aspect, i) => (
              <tr key={i} className={aspect.agreement ? 'ct-row-agree' : 'ct-row-disagree'}>
                <td className="ct-aspect-cell">{aspect.aspect}</td>
                {models.map((m) => {
                  const val = aspect.values[m.key];
                  const verdictColor = aspect.aspect === 'Verdict' ? getVerdictColor(val) : '';
                  return (
                    <td key={m.key} className="ct-value-cell" style={verdictColor ? { color: verdictColor } : undefined}>
                      {formatValue(val ?? 'N/A')}
                    </td>
                  );
                })}
                <td className="ct-agree-cell">
                  {aspect.agreement ? (
                    <span className="ct-agree-badge">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
                      Agree
                    </span>
                  ) : (
                    <span className="ct-disagree-badge">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                      Differ
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Summary stats */}
      <div className="comparison-summary">
        <div className="comparison-stat">
          <span className="comparison-stat-val" style={{ color: '#6ee7b7' }}>
            {comparison.aspects.filter((a) => a.agreement).length}
          </span>
          <span className="comparison-stat-label">Agreements</span>
        </div>
        <div className="comparison-stat">
          <span className="comparison-stat-val" style={{ color: '#f87171' }}>
            {comparison.aspects.filter((a) => !a.agreement).length}
          </span>
          <span className="comparison-stat-label">Differences</span>
        </div>
        <div className="comparison-stat">
          <span className="comparison-stat-val">
            {comparison.models.length}
          </span>
          <span className="comparison-stat-label">Models</span>
        </div>
      </div>
    </div>
  );
});

export default ComparisonTable;
