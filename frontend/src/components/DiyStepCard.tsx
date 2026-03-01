import { useState, memo } from 'react';
import type { DiyStep, StepSafetyAnalysis, MatchedRule } from '@/types';
import { SEVERITY_COLORS } from '@/constants';

interface DiyStepCardProps {
  step: DiyStep;
  analysis?: StepSafetyAnalysis;
  forceExpanded?: boolean;
  index?: number;
  isSelected?: boolean;
  onSelect?: (stepNumber: number) => void;
}

function SeverityBadge({ severity }: { severity: number }) {
  const config = SEVERITY_COLORS[severity] ?? SEVERITY_COLORS[3];
  return (
    <span
      className="safety-severity-badge"
      style={{ background: `${config.color}20`, color: config.color }}
      title={`Severity ${severity}: ${config.label}`}
    >
      {severity}
    </span>
  );
}

function RuleItem({ rule }: { rule: MatchedRule }) {
  return (
    <div className="match-item match-violation">
      <div className="flex items-start gap-2">
        <SeverityBadge severity={rule.severity} />
        <div className="flex-1 min-w-0">
          <p className="text-sm leading-relaxed">{rule.rule_text}</p>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="safety-category-pill">{rule.category}</span>
            <span className="text-xs text-muted italic">{rule.relevance}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function PrecautionList({
  items,
  colorClass,
  icon,
}: {
  items: string[];
  colorClass: string;
  icon: 'check' | 'warning' | 'x';
}) {
  if (items.length === 0) return null;

  const iconSvg = icon === 'check' ? (
    <svg className="shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
  ) : icon === 'warning' ? (
    <svg className="shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
  ) : (
    <svg className="shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
  );

  return (
    <ul className="space-y-1">
      {items.map((item, i) => (
        <li key={i} className={`flex items-start gap-2 text-xs ${colorClass}`}>
          {iconSvg}
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

const DiyStepCard = memo(function DiyStepCard({ step, analysis, forceExpanded, index = 0, isSelected, onSelect }: DiyStepCardProps) {
  const [localExpanded, setLocalExpanded] = useState(false);
  const expanded = forceExpanded ?? localExpanded;

  const issueCount = analysis
    ? analysis.missing_precautions.length + analysis.matched_rules.length
    : 0;
  const hasIssues = analysis ? analysis.missing_precautions.length > 0 : false;

  const riskClass = analysis
    ? analysis.risk_level >= 5
      ? 'risk-critical'
      : analysis.risk_level >= 4
        ? 'risk-high'
        : analysis.risk_level >= 3
          ? 'risk-medium'
          : 'risk-low'
    : 'risk-none';

  const handleClick = () => {
    setLocalExpanded(!localExpanded);
    if (onSelect) {
      onSelect(step.step_number);
    }
  };

  return (
    <div
      className={`step-timeline-item ${riskClass} ${isSelected ? 'step-selected' : ''}`}
      style={{ '--entrance-index': index } as React.CSSProperties}
    >
      {/* Compact header — horizontal block */}
      <button
        onClick={handleClick}
        className="step-timeline-header"
      >
        <span className={`step-number ${hasIssues ? 'step-number-warn' : analysis ? 'step-number-safe' : ''}`}>
          {step.step_number}
        </span>
        <span className="step-timeline-title">{step.action_summary}</span>
        <div className="step-timeline-badges">
          {analysis && (
            <span className="step-risk-pill" style={{
              background: analysis.risk_level >= 4 ? 'rgba(248,113,113,0.15)' : analysis.risk_level >= 3 ? 'rgba(251,146,60,0.15)' : 'rgba(110,231,183,0.15)',
              color: analysis.risk_level >= 4 ? '#f87171' : analysis.risk_level >= 3 ? '#fb923c' : '#6ee7b7',
            }}>
              {analysis.risk_level}/5
            </span>
          )}
          {hasIssues ? (
            <span className="issue-count-badge">{analysis!.missing_precautions.length}</span>
          ) : analysis ? (
            <span className="safe-badge">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
            </span>
          ) : null}
        </div>
        <svg
          className={`step-chevron ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expandable content */}
      <div className={`step-card-collapse ${expanded ? 'step-card-collapse-open' : ''}`}>
        <div className="step-card-collapse-inner">
          <div className="step-expand-content">
            {/* Step instruction text */}
            {step.step_text && (
              <div>
                <h4 className="section-label">Instruction</h4>
                <p className="text-sm leading-relaxed">{step.step_text}</p>
              </div>
            )}

            {/* Transcript excerpt */}
            {step.transcript_excerpt && (
              <div>
                <h4 className="section-label">Transcript Excerpt</h4>
                <p className="text-xs text-muted italic leading-relaxed">&ldquo;{step.transcript_excerpt}&rdquo;</p>
              </div>
            )}

            {/* Safety analysis results */}
            {analysis ? (
              <div className="space-y-3 pt-1">
                <div className="safety-analysis-divider">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                  <span>Safety Analysis</span>
                </div>

                {/* Required precautions */}
                {analysis.required_precautions.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-blue-400 mb-1.5">Required Precautions ({analysis.required_precautions.length})</h4>
                    <PrecautionList items={analysis.required_precautions} colorClass="text-blue-400" icon="warning" />
                  </div>
                )}

                {/* Already mentioned in video */}
                {analysis.already_mentioned_precautions.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-1.5">Already Mentioned ({analysis.already_mentioned_precautions.length})</h4>
                    <PrecautionList items={analysis.already_mentioned_precautions} colorClass="text-emerald-400" icon="check" />
                  </div>
                )}

                {/* Missing precautions */}
                {analysis.missing_precautions.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-orange-400 mb-1.5">Missing Precautions ({analysis.missing_precautions.length})</h4>
                    <PrecautionList items={analysis.missing_precautions} colorClass="text-orange-400" icon="x" />
                  </div>
                )}

                {/* Matched rules */}
                {analysis.matched_rules.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-yellow-400 mb-1.5">Matched Safety Rules ({analysis.matched_rules.length})</h4>
                    <div className="space-y-2">
                      {analysis.matched_rules.map((rule, i) => (
                        <RuleItem key={`r-${i}`} rule={rule} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
});

export default DiyStepCard;
