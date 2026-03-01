import { memo } from 'react';
import type { SafetyReport } from '@/types';
import { VERDICT_CONFIG } from '@/constants';

interface VerdictCardProps {
    report: SafetyReport;
}

const VerdictCard = memo(function VerdictCard({ report }: VerdictCardProps) {
    const config = VERDICT_CONFIG[report.verdict];
    const totalMissing = report.step_safety_analysis.reduce(
        (sum, s) => sum + s.missing_precautions.length, 0
    );
    const stepsAnalyzed = report.step_safety_analysis.length;

    // Risk score as percentage of 5
    const riskPct = Math.min((report.overall_risk_score / 5) * 100, 100);
    const criticalPct = Math.min(report.critical_concerns.length * 20, 100);
    const missingPct = stepsAnalyzed > 0 ? Math.min((totalMissing / stepsAnalyzed) * 50, 100) : 0;

    return (
        <div
            className="verdict-card"
            style={{ '--v-color': config.color, '--v-bg': config.bgColor } as React.CSSProperties}
        >
            {/* Main verdict row */}
            <div className="vc-top">
                <div className="vc-verdict-block">
                    <span className="vc-icon" style={{ background: config.bgColor, color: config.color }}>
                        {config.icon}
                    </span>
                    <div>
                        <h2 className="vc-label" style={{ color: config.color }}>{config.label}</h2>
                        <p className="vc-desc">{config.description}</p>
                    </div>
                </div>
                <div className="vc-scores">
                    <div className="vc-score-item">
                        <span className="vc-score-val" style={{ color: config.color }}>
                            {report.overall_risk_score.toFixed(1)}
                        </span>
                        <span className="vc-score-label">Risk / 5</span>
                    </div>
                </div>
            </div>

            {/* Metric bars */}
            <div className="vc-bars">
                <div className="vc-bar-row">
                    <span className="vc-bar-label">Critical Issues</span>
                    <div className="vc-bar-track">
                        <div
                            className="vc-bar-fill vc-bar-critical"
                            style={{ width: `${criticalPct}%` }}
                        />
                    </div>
                    <span className="vc-bar-val" style={{ color: '#f87171' }}>{report.critical_concerns.length}</span>
                </div>
                <div className="vc-bar-row">
                    <span className="vc-bar-label">Missing Precautions</span>
                    <div className="vc-bar-track">
                        <div
                            className="vc-bar-fill vc-bar-missing"
                            style={{ width: `${missingPct}%` }}
                        />
                    </div>
                    <span className="vc-bar-val" style={{ color: '#fb923c' }}>{totalMissing}</span>
                </div>
                <div className="vc-bar-row">
                    <span className="vc-bar-label">Steps Analyzed</span>
                    <div className="vc-bar-track">
                        <div
                            className="vc-bar-fill vc-bar-steps"
                            style={{ width: '100%' }}
                        />
                    </div>
                    <span className="vc-bar-val">{stepsAnalyzed}</span>
                </div>
            </div>
        </div>
    );
});

export default VerdictCard;
