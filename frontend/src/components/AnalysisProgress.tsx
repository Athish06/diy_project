import { memo } from 'react';
import type { AnalysisPhase } from '@/types';

interface AnalysisProgressProps {
  phase: AnalysisPhase;
  elapsedMs: number;
  statusMessage: string;
}

const PHASES = [
  { key: 'fetching', label: 'Transcript', icon: '↓' },
  { key: 'extracting', label: 'Extraction', icon: '⚙' },
  { key: 'analyzing', label: 'Safety', icon: '⛨' },
  { key: 'complete', label: 'Done', icon: '✓' },
] as const;

function phaseIndex(phase: AnalysisPhase): number {
  const idx = PHASES.findIndex((p) => p.key === phase);
  return idx >= 0 ? idx : -1;
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

const AnalysisProgress = memo(function AnalysisProgress({
  phase,
  elapsedMs,
  statusMessage,
}: AnalysisProgressProps) {
  if (phase === 'idle') return null;

  const current = phaseIndex(phase);
  const isError = phase === 'error';

  return (
    <div className="analysis-progress glass-card animate-fade-in">
      {/* Phase stepper */}
      <div className="progress-stepper">
        {PHASES.map((p, i) => {
          const isActive = i === current;
          const isDone = i < current;
          const stateClass = isError && isActive
            ? 'progress-step-error'
            : isDone
              ? 'progress-step-done'
              : isActive
                ? 'progress-step-active'
                : 'progress-step-pending';

          return (
            <div key={p.key} className="progress-step-wrapper">
              {/* Connector line */}
              {i > 0 && (
                <div className={`progress-connector ${isDone ? 'progress-connector-done' : ''}`} />
              )}
              <div className={`progress-step ${stateClass}`}>
                <span className="progress-step-icon">{isDone ? '✓' : p.icon}</span>
              </div>
              <span className={`progress-step-label ${isActive ? 'text-foreground' : 'text-muted'}`}>
                {p.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Status text + elapsed timer */}
      <div className="progress-footer">
        <p className="progress-status">{statusMessage}</p>
        {phase !== 'complete' && elapsedMs > 0 && (
          <span className="progress-timer">{formatElapsed(elapsedMs)}</span>
        )}
      </div>
    </div>
  );
});

export default AnalysisProgress;
