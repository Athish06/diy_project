import { memo } from 'react';
import type { SafetyReport } from '@/types';
import { VERDICT_CONFIG } from '@/constants';

interface ComplianceVerdictProps {
  report: SafetyReport;
}

function SeverityGauge({ score, color }: { score: number; color: string }) {
  const pct = Math.min(score / 5, 1);
  const circumference = 2 * Math.PI * 36;
  const offset = circumference * (1 - pct);

  return (
    <div className="severity-gauge">
      <svg width="88" height="88" viewBox="0 0 88 88">
        {/* Track */}
        <circle
          cx="44" cy="44" r="36"
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="6"
        />
        {/* Value arc */}
        <circle
          cx="44" cy="44" r="36"
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 44 44)"
          className="gauge-arc"
        />
      </svg>
      <div className="gauge-label">
        <span className="gauge-value" style={{ color }}>{score.toFixed(1)}</span>
        <span className="gauge-max">/ 5.0</span>
      </div>
    </div>
  );
}

const ComplianceVerdictBanner = memo(function ComplianceVerdictBanner({ report }: ComplianceVerdictProps) {
  const config = VERDICT_CONFIG[report.verdict];

  const totalMissing = report.step_safety_analysis.reduce(
    (sum, s) => sum + s.missing_precautions.length, 0
  );

  return (
    <div
      className={`compliance-verdict glass-card ${report.verdict === 'SAFE' ? 'verdict-safe' : report.verdict === 'PROFESSIONAL_REQUIRED' ? 'verdict-pro' : 'verdict-unsafe'}`}
      style={{ '--verdict-color': config.color, '--verdict-bg': config.bgColor } as React.CSSProperties}
    >
      <div className="verdict-top">
        {/* Left: icon + label */}
        <div className="flex items-center gap-4 flex-1 min-w-0">
          <div className="verdict-icon" style={{ background: config.bgColor, color: config.color }}>
            {config.icon}
          </div>
          <div>
            <h2 className="verdict-label" style={{ color: config.color }}>
              {config.label}
            </h2>
            <p className="text-xs text-muted mt-0.5">{config.description}</p>
          </div>
        </div>

        {/* Right: gauge */}
        <SeverityGauge score={report.overall_risk_score} color={config.color} />
      </div>

      {/* Summary */}
      {report.summary && (
        <p className="text-sm leading-relaxed mt-3 px-1">{report.summary}</p>
      )}

      {/* Stats row */}
      <div className="verdict-stats">
        <div className="verdict-stat">
          <span className="verdict-stat-count text-red-400">{report.critical_concerns.length}</span>
          <span className="verdict-stat-label">Critical Concerns</span>
        </div>
        <div className="verdict-stat">
          <span className="verdict-stat-count text-orange-400">{totalMissing}</span>
          <span className="verdict-stat-label">Missing Precautions</span>
        </div>
        <div className="verdict-stat">
          <span className="verdict-stat-count text-muted">{report.step_safety_analysis.length}</span>
          <span className="verdict-stat-label">Steps Analyzed</span>
        </div>
      </div>

      {/* Parent monitoring */}
      {report.parent_monitoring_required && (
        <div className="flex items-start gap-2 mt-3 px-1 py-2 rounded-lg" style={{ background: 'rgba(251, 146, 60, 0.08)' }}>
          <svg className="shrink-0 mt-0.5 text-orange-400" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          <div>
            <span className="text-xs font-semibold text-orange-400 uppercase tracking-wider">Parent Monitoring Required</span>
            <p className="text-xs text-muted mt-0.5">{report.parent_monitoring_reason}</p>
          </div>
        </div>
      )}

      {/* Critical concerns */}
      {report.critical_concerns.length > 0 && (
        <div className="mt-3 space-y-1">
          <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wider px-1">Critical Concerns</h4>
          {report.critical_concerns.map((concern, i) => (
            <div key={i} className="flex items-start gap-2 px-1">
              <svg className="shrink-0 mt-0.5 text-red-400" width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"/></svg>
              <span className="text-xs text-red-300">{concern}</span>
            </div>
          ))}
        </div>
      )}

      {/* Safety measures already in video */}
      {report.safety_measures_in_video.length > 0 && (
        <div className="mt-3 space-y-1">
          <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider px-1">Safety Measures in Video</h4>
          <div className="flex flex-wrap gap-1.5 px-1">
            {report.safety_measures_in_video.map((m, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(110, 231, 183, 0.1)', color: '#6ee7b7' }}>{m}</span>
            ))}
          </div>
        </div>
      )}

      {/* Recommended additional measures */}
      {report.recommended_additional_measures.length > 0 && (
        <div className="mt-3 space-y-1">
          <h4 className="text-xs font-semibold text-yellow-400 uppercase tracking-wider px-1">Recommended Additional Measures</h4>
          <div className="flex flex-wrap gap-1.5 px-1">
            {report.recommended_additional_measures.map((m, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(252, 211, 77, 0.1)', color: '#fcd34d' }}>{m}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
});

export default ComplianceVerdictBanner;
