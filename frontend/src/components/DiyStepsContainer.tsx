import { useState, useMemo, memo, useCallback } from 'react';
import type { DiyStep, DiyExtraction, StepSafetyAnalysis, SafetyReport } from '@/types';
import ComplianceVerdictBanner from './ComplianceVerdict';
import DiyStepCard from './DiyStepCard';

type FilterMode = 'all' | 'issues' | 'safe';

interface DiyStepsContainerProps {
  steps: DiyStep[];
  extraction: DiyExtraction | null;
  report: SafetyReport | null;
  isAnalyzing: boolean;
}

const DiyStepsContainer = memo(function DiyStepsContainer({
  steps,
  extraction,
  report,
  isAnalyzing,
}: DiyStepsContainerProps) {
  const [allExpanded, setAllExpanded] = useState(false);
  const [filter, setFilter] = useState<FilterMode>('all');

  const analysisMap = useMemo(() => {
    const map = new Map<number, StepSafetyAnalysis>();
    if (report) {
      for (const sa of report.step_safety_analysis) {
        map.set(sa.step_number, sa);
      }
    }
    return map;
  }, [report]);

  const counts = useMemo(() => {
    if (!report) return { issues: 0, safe: 0 };
    let issues = 0;
    let safe = 0;
    for (const sa of report.step_safety_analysis) {
      if (sa.missing_precautions.length > 0 || sa.risk_level >= 4) {
        issues++;
      } else {
        safe++;
      }
    }
    return { issues, safe };
  }, [report]);

  const filteredSteps = useMemo(() => {
    if (!report || filter === 'all') return steps;
    return steps.filter((s) => {
      const a = analysisMap.get(s.step_number);
      if (!a) return true;
      const hasIssues = a.missing_precautions.length > 0 || a.risk_level >= 4;
      return filter === 'issues' ? hasIssues : !hasIssues;
    });
  }, [steps, report, filter, analysisMap]);

  const handleExportJson = useCallback(() => {
    const data = { steps, safety_report: report };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'diy-safety-report.json';
    a.click();
    URL.revokeObjectURL(url);
  }, [steps, report]);

  if (steps.length === 0) return null;

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Compliance verdict banner */}
      {report ? (
        <ComplianceVerdictBanner report={report} />
      ) : isAnalyzing ? (
        <div className="glass-card px-5 py-4 analyzing-card">
          <div className="flex items-center gap-3">
            <div className="analyzing-spinner" />
            <div>
              <span className="text-sm font-medium">Running safety compliance analysis...</span>
              <p className="text-xs text-muted mt-0.5">Matching {steps.length} steps against safety rule database</p>
            </div>
          </div>
          <div className="analyzing-shimmer-bar" />
        </div>
      ) : null}

      {/* Extraction overview */}
      {extraction && (
        <div className="glass-card px-5 py-4 space-y-3 animate-fade-in">
          {extraction.diy_categories.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {extraction.diy_categories.map((cat) => (
                <span key={cat} className="safety-category-pill">{cat}</span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-4">
            {extraction.tools.length > 0 && (
              <div>
                <h4 className="section-label">Tools</h4>
                <div className="flex flex-wrap gap-1.5">
                  {extraction.tools.map((tool) => (
                    <span key={tool} className="tool-pill">{tool}</span>
                  ))}
                </div>
              </div>
            )}
            {extraction.materials.length > 0 && (
              <div>
                <h4 className="section-label">Materials</h4>
                <div className="flex flex-wrap gap-1.5">
                  {extraction.materials.map((mat) => (
                    <span key={mat} className="material-pill">{mat}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
          {extraction.safety_precautions.length > 0 && (
            <div>
              <h4 className="section-label">Safety Precautions</h4>
              <ul className="space-y-1">
                {extraction.safety_precautions.map((p, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-orange-400">
                    <svg className="shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Action bar with filter tabs */}
      <div className="steps-action-bar">
        <div className="flex items-center gap-1">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mr-2">
            {steps.length} Steps
          </h3>
          {report && (
            <div className="filter-tabs">
              <button
                onClick={() => setFilter('all')}
                className={`filter-tab ${filter === 'all' ? 'filter-tab-active' : ''}`}
              >
                All
              </button>
              <button
                onClick={() => setFilter('issues')}
                className={`filter-tab filter-tab-issues ${filter === 'issues' ? 'filter-tab-active' : ''}`}
              >
                Issues
                {counts.issues > 0 && <span className="filter-tab-count">{counts.issues}</span>}
              </button>
              <button
                onClick={() => setFilter('safe')}
                className={`filter-tab filter-tab-safe ${filter === 'safe' ? 'filter-tab-active' : ''}`}
              >
                Safe
                {counts.safe > 0 && <span className="filter-tab-count">{counts.safe}</span>}
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAllExpanded(!allExpanded)}
            className="action-btn-sm"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              {allExpanded ? (
                <><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></>
              ) : (
                <><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></>
              )}
            </svg>
            {allExpanded ? 'Collapse' : 'Expand'}
          </button>
          <button onClick={handleExportJson} className="action-btn-sm">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Export
          </button>
        </div>
      </div>

      {/* Step cards */}
      <div className="space-y-2">
        {filteredSteps.map((step, i) => (
          <DiyStepCard
            key={step.step_number}
            step={step}
            analysis={analysisMap.get(step.step_number)}
            forceExpanded={allExpanded}
            index={i}
          />
        ))}
        {filteredSteps.length === 0 && filter !== 'all' && (
          <div className="glass-card px-5 py-8 text-center">
            <p className="text-sm text-muted">No steps match this filter.</p>
            <button onClick={() => setFilter('all')} className="text-xs text-accent mt-2 hover:underline">
              Show all steps
            </button>
          </div>
        )}
      </div>
    </div>
  );
});

export default DiyStepsContainer;
