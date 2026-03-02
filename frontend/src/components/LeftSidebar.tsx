import { memo, useCallback } from 'react';
import type { SafetyReport, ComplianceVerdict } from '@/types';

interface HistoryEntry {
    scanId: number;
    id: string;
    videoId: string;
    title: string;
    channel: string;
    verdict: ComplianceVerdict;
    riskScore: number;
    confidence: number;
    date: string;
}

interface LeftSidebarProps {
    onNewAnalysis: () => void;
    onOpenSettings: () => void;
    history: HistoryEntry[];
    onLoadHistory: (entry: HistoryEntry) => void;
    activeVideoId: string | null;
}

const MODEL_ENSEMBLE = [
    { name: 'LLM A', desc: 'Groq LLaMA', active: true },
    { name: 'LLM B', desc: 'Reviewer', active: true },
    { name: 'Aggregator', desc: 'Final Model', active: true },
];

const VERDICT_BADGE: Record<ComplianceVerdict, { label: string; cls: string }> = {
    SAFE: { label: 'Safe', cls: 'verdict-badge-safe' },
    UNSAFE: { label: 'Unsafe', cls: 'verdict-badge-unsafe' },
    PROFESSIONAL_REQUIRED: { label: 'Caution', cls: 'verdict-badge-caution' },
};

const LeftSidebar = memo(function LeftSidebar({
    onNewAnalysis,
    onOpenSettings,
    history,
    onLoadHistory,
    activeVideoId,
}: LeftSidebarProps) {
    return (
        <aside className="left-sidebar">
            {/* App name */}
            <div className="sidebar-header">
                <h1 className="sidebar-brand">DIY-Safety</h1>
                <button onClick={onOpenSettings} className="sidebar-settings-btn" aria-label="Settings" title="Settings">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                </button>
            </div>

            {/* New Analysis button */}
            <button onClick={onNewAnalysis} className="sidebar-new-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                New Analysis
            </button>

            <div className="sidebar-divider" />

            {/* History list */}
            <div className="sidebar-section-label">History</div>
            <div className="sidebar-history">
                {history.length === 0 ? (
                    <p className="sidebar-empty">No analyses yet. Paste a YouTube URL to get started.</p>
                ) : (
                    history.map((entry) => {
                        const badge = VERDICT_BADGE[entry.verdict] ?? VERDICT_BADGE['SAFE'];
                        return (
                            <button
                                key={entry.id}
                                onClick={() => onLoadHistory(entry)}
                                className={`sidebar-history-item ${activeVideoId === entry.videoId ? 'active' : ''}`}
                            >
                                <img
                                    src={`https://img.youtube.com/vi/${entry.videoId}/default.jpg`}
                                    alt=""
                                    className="sidebar-thumb"
                                    loading="lazy"
                                />
                                <div className="sidebar-history-info">
                                    <span className="sidebar-history-title">{entry.title}</span>
                                    <div className="sidebar-history-meta">
                                        <span className={`sidebar-verdict-badge ${badge.cls}`}>{badge.label}</span>
                                        <span className="sidebar-history-confidence">{entry.confidence}%</span>
                                    </div>
                                    <span className="sidebar-history-date">{entry.date}</span>
                                </div>
                            </button>
                        );
                    })
                )}
            </div>

            <div className="sidebar-divider" />

            {/* Model Ensemble Info */}
            <div className="sidebar-section-label">Model Ensemble</div>
            <div className="sidebar-models">
                {MODEL_ENSEMBLE.map((m) => (
                    <div key={m.name} className="sidebar-model-row">
                        <span className={`sidebar-model-indicator ${m.active ? 'active' : 'disabled'}`} />
                        <span className="sidebar-model-name">{m.name}</span>
                        <span className="sidebar-model-desc">{m.desc}</span>
                    </div>
                ))}
            </div>
        </aside>
    );
});

export type { HistoryEntry };
export default LeftSidebar;
