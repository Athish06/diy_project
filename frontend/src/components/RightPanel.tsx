import { memo } from 'react';
import type { SafetyReport, StepSafetyAnalysis } from '@/types';
import { VERDICT_CONFIG, SEVERITY_COLORS } from '@/constants';

interface RightPanelProps {
    report: SafetyReport | null;
    selectedStep: StepSafetyAnalysis | null;
    isAnalyzing: boolean;
}

const RightPanel = memo(function RightPanel({ report, selectedStep, isAnalyzing }: RightPanelProps) {
    if (!report && !isAnalyzing) {
        return (
            <aside className="right-panel">
                <div className="right-panel-empty">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="right-panel-empty-icon">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    </svg>
                    <p className="right-panel-empty-title">Safety Intelligence</p>
                    <p className="right-panel-empty-desc">Analyze a video to see safety findings here.</p>
                </div>
            </aside>
        );
    }

    if (isAnalyzing && !report) {
        return (
            <aside className="right-panel">
                <div className="right-panel-loading">
                    <div className="analyzing-spinner" />
                    <p>Running safety analysis…</p>
                </div>
            </aside>
        );
    }

    if (!report) return null;

    const config = VERDICT_CONFIG[report.verdict];
    const totalMissing = report.step_safety_analysis.reduce(
        (sum, s) => sum + s.missing_precautions.length, 0
    );

    // If a step is selected, show step-specific analysis
    if (selectedStep) {
        const riskColor = SEVERITY_COLORS[selectedStep.risk_level] ?? SEVERITY_COLORS[3];
        return (
            <aside className="right-panel">
                <div className="rp-section">
                    <h3 className="rp-section-title">
                        Step {selectedStep.step_number} — Safety Analysis
                    </h3>
                    <div className="rp-risk-row">
                        <span className="rp-risk-label">Risk Level</span>
                        <span className="rp-risk-value" style={{ color: riskColor.color }}>
                            {selectedStep.risk_level}/5
                        </span>
                    </div>
                </div>

                {/* Missing precautions */}
                {selectedStep.missing_precautions.length > 0 && (
                    <div className="rp-section">
                        <h4 className="rp-subsection-title rp-danger">Missing Precautions</h4>
                        <ul className="rp-list rp-list-danger">
                            {selectedStep.missing_precautions.map((p, i) => (
                                <li key={i}>{p}</li>
                            ))}
                        </ul>
                    </div>
                )}

                {/* Required precautions */}
                {selectedStep.required_precautions.length > 0 && (
                    <div className="rp-section">
                        <h4 className="rp-subsection-title rp-warn">Required Precautions</h4>
                        <ul className="rp-list rp-list-warn">
                            {selectedStep.required_precautions.map((p, i) => (
                                <li key={i}>{p}</li>
                            ))}
                        </ul>
                    </div>
                )}

                {/* Already mentioned */}
                {selectedStep.already_mentioned_precautions.length > 0 && (
                    <div className="rp-section">
                        <h4 className="rp-subsection-title rp-safe">Already Mentioned</h4>
                        <ul className="rp-list rp-list-safe">
                            {selectedStep.already_mentioned_precautions.map((p, i) => (
                                <li key={i}>{p}</li>
                            ))}
                        </ul>
                    </div>
                )}

                {/* Matched rules */}
                {selectedStep.matched_rules.length > 0 && (
                    <div className="rp-section">
                        <h4 className="rp-subsection-title">Matched Safety Rules</h4>
                        <div className="rp-rules">
                            {selectedStep.matched_rules.map((rule, i) => {
                                const sev = SEVERITY_COLORS[rule.severity] ?? SEVERITY_COLORS[3];
                                return (
                                    <div key={i} className="rp-rule-item">
                                        <span className="rp-rule-severity" style={{ color: sev.color, background: `${sev.color}15` }}>
                                            {rule.severity}
                                        </span>
                                        <div className="rp-rule-content">
                                            <p className="rp-rule-text">{rule.rule_text}</p>
                                            <span className="rp-rule-category">{rule.category}</span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </aside>
        );
    }

    // Overall safety intelligence
    return (
        <aside className="right-panel">
            {/* Verdict */}
            <div className="rp-section">
                <h3 className="rp-section-title">Overall Verdict</h3>
                <div className="rp-verdict-card" style={{ borderColor: config.color }}>
                    <span className="rp-verdict-label" style={{ color: config.color }}>{config.label}</span>
                    <span className="rp-verdict-icon" style={{ color: config.color }}>{config.icon}</span>
                </div>
                <p className="rp-verdict-desc">{report.summary}</p>
            </div>

            {/* Stats */}
            <div className="rp-section">
                <h4 className="rp-subsection-title">Metrics</h4>
                <div className="rp-metrics">
                    <div className="rp-metric">
                        <span className="rp-metric-value" style={{ color: '#f87171' }}>{report.critical_concerns.length}</span>
                        <span className="rp-metric-label">Critical Issues</span>
                    </div>
                    <div className="rp-metric">
                        <span className="rp-metric-value" style={{ color: '#fb923c' }}>{totalMissing}</span>
                        <span className="rp-metric-label">Missing Precautions</span>
                    </div>
                    <div className="rp-metric">
                        <span className="rp-metric-value">{report.step_safety_analysis.length}</span>
                        <span className="rp-metric-label">Steps Analyzed</span>
                    </div>
                </div>
            </div>

            {/* Critical concerns */}
            {report.critical_concerns.length > 0 && (
                <div className="rp-section">
                    <h4 className="rp-subsection-title rp-danger">Critical Concerns</h4>
                    <ul className="rp-list rp-list-danger">
                        {report.critical_concerns.map((c, i) => (
                            <li key={i}>{c}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Parent monitoring */}
            {report.parent_monitoring_required && (
                <div className="rp-section">
                    <div className="rp-monitoring-alert">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
                        <div>
                            <span className="rp-monitoring-title">Parent Monitoring Required</span>
                            <p className="rp-monitoring-reason">{report.parent_monitoring_reason}</p>
                        </div>
                    </div>
                </div>
            )}

            {/* Recommended measures */}
            {report.recommended_additional_measures.length > 0 && (
                <div className="rp-section">
                    <h4 className="rp-subsection-title rp-warn">Recommended Additions</h4>
                    <ul className="rp-list rp-list-warn">
                        {report.recommended_additional_measures.map((m, i) => (
                            <li key={i}>{m}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Safety measures in video */}
            {report.safety_measures_in_video.length > 0 && (
                <div className="rp-section">
                    <h4 className="rp-subsection-title rp-safe">Safety Measures in Video</h4>
                    <div className="rp-pills">
                        {report.safety_measures_in_video.map((m, i) => (
                            <span key={i} className="rp-pill-safe">{m}</span>
                        ))}
                    </div>
                </div>
            )}

            <div className="rp-hint">Click a step to see detailed analysis</div>
        </aside>
    );
});

export default RightPanel;
