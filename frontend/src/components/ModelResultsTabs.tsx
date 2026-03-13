import { useState, useMemo, memo, useCallback } from 'react';
import type { ModelReport, ModelComparison, DiyStep, StepSafetyAnalysis } from '@/types';
import VerdictCard from './VerdictCard';
import DiyStepCard from './DiyStepCard';
import ComparisonTable from '@/components/ComparisonTable';

interface ModelResultsTabsProps {
  modelReports: Record<string, ModelReport>;
  comparison: ModelComparison | null;
  steps: DiyStep[];
  isAnalyzing: boolean;
  selectedStep: number | null;
  onStepSelect: (stepNumber: number) => void;
}

const MODEL_COLORS: Record<string, string> = {
  qwen: '#7c3aed', // violet-600
  gpt_oss: '#2563eb', // blue-600
};

const MODEL_ORDER = ['qwen', 'gpt_oss'];

const ModelResultsTabs = memo(function ModelResultsTabs({
  modelReports,
  comparison,
  steps,
  isAnalyzing,
  selectedStep,
  onStepSelect,
}: ModelResultsTabsProps) {
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [showComparison, setShowComparison] = useState(false);
  const [allExpanded, setAllExpanded] = useState(false);

  const sortedKeys = useMemo(() => {
    return MODEL_ORDER.filter((k) => k in modelReports);
  }, [modelReports]);

  const resolvedActiveTab = activeTab && modelReports[activeTab] ? activeTab : sortedKeys[0] ?? null;
  const activeReport = resolvedActiveTab ? modelReports[resolvedActiveTab] : null;

  const analysisMap = useMemo(() => {
    const map = new Map<number, StepSafetyAnalysis>();
    if (activeReport) {
      for (const sa of activeReport.report.step_safety_analysis) {
        map.set(sa.step_number, sa);
      }
    }
    return map;
  }, [activeReport]);

  const handleToggleComparison = useCallback(() => {
    setShowComparison((prev) => !prev);
  }, []);

  if (sortedKeys.length === 0) {
    if (!isAnalyzing) return null;
    return (
      <div className="glass-card px-5 py-4 analyzing-card">
        <div className="flex items-center gap-3">
          <div className="analyzing-spinner" />
          <div>
            <span className="text-sm font-medium">Running safety compliance analysis...</span>
            <p className="text-xs text-muted mt-0.5">Matching {steps.length} steps against safety rule database using 3 models</p>
          </div>
        </div>
        <div className="analyzing-shimmer-bar" />
      </div>
    );
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Model tabs bar */}
      <div className="model-tabs-container">
        <div className="model-tabs">
          {sortedKeys.map((key) => {
            const mr = modelReports[key];
            const color = MODEL_COLORS[key] || '#a78bfa';
            const isActive = key === resolvedActiveTab;
            return (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`model-tab ${isActive ? 'model-tab-active' : ''}`}
                style={{
                  '--tab-color': color,
                  borderBottomColor: isActive ? color : 'transparent',
                } as React.CSSProperties}
              >
                <span className="model-tab-dot" style={{ background: color }} />
                <span className="model-tab-label">{mr.label}</span>
                <span
                  className="model-tab-verdict"
                  style={{ color }}
                >
                  {mr.report.verdict === 'SAFE' ? '✓' : mr.report.verdict === 'UNSAFE' ? '✕' : '⚠'}
                </span>
              </button>
            );
          })}
        </div>

        {/* Compare Results button */}
        {comparison && comparison.aspects.length > 0 && (
          <button
            onClick={handleToggleComparison}
            className={`compare-results-btn ${showComparison ? 'compare-results-btn-active' : ''}`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" />
              <rect x="14" y="3" width="7" height="7" />
              <rect x="14" y="14" width="7" height="7" />
              <rect x="3" y="14" width="7" height="7" />
            </svg>
            {showComparison ? 'Hide Comparison' : 'Compare Results'}
          </button>
        )}
      </div>

      {/* Comparison table */}
      {showComparison && comparison && (
        <ComparisonTable comparison={comparison} modelColors={MODEL_COLORS} />
      )}

      {/* Active model's verdict card */}
      {activeReport && (
        <div className="model-result-section">
          <VerdictCard report={activeReport.report} />
        </div>
      )}

      {/* Active model's step analysis */}
      {activeReport && (
        <>
          <div className="steps-action-bar">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-muted uppercase tracking-wider">
                Step Analysis — {activeReport.label}
              </h3>
            </div>
            <button
              onClick={() => setAllExpanded(!allExpanded)}
              className="action-btn-sm"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {allExpanded ? (
                  <><polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" /><line x1="14" y1="10" x2="21" y2="3" /><line x1="3" y1="21" x2="10" y2="14" /></>
                ) : (
                  <><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></>
                )}
              </svg>
              {allExpanded ? 'Collapse' : 'Expand'}
            </button>
          </div>

          <div className="step-timeline">
            {steps.map((step, i) => (
              <DiyStepCard
                key={step.step_number}
                step={step}
                analysis={analysisMap.get(step.step_number)}
                forceExpanded={allExpanded}
                index={i}
                isSelected={step.step_number === selectedStep}
                onSelect={() => onStepSelect(step.step_number)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
});

export default ModelResultsTabs;
