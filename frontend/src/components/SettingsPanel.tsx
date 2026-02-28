import { useState, useEffect } from 'react';
import { checkHealth } from '@/lib/api';

interface SettingsPanelProps {
  onClose: () => void;
}

export default function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [health, setHealth] = useState<{
    api_key_configured: boolean;
    database_configured: boolean;
    model: string;
  } | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    checkHealth().then(setHealth).catch(() => {});
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-overlay">
      <div
        className="w-full max-w-sm h-full bg-background border-l border-card-border p-6 overflow-y-auto"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-foreground p-1 transition-colors"
            aria-label="Close settings"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* System Status */}
        {health && (
          <div className="space-y-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">System Status</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm">API Key</span>
                <span className={`text-xs font-medium ${health.api_key_configured ? 'text-emerald-400' : 'text-red-400'}`}>
                  {health.api_key_configured ? 'Configured' : 'Missing'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Database</span>
                <span className={`text-xs font-medium ${health.database_configured ? 'text-emerald-400' : 'text-red-400'}`}>
                  {health.database_configured ? 'Connected' : 'Not configured'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">Model</span>
                <span className="text-xs font-medium text-muted">{health.model}</span>
              </div>
            </div>
            <p className="text-xs text-muted mt-4">
              API key and database connection are configured via the <code>.env</code> file in the backend directory.
            </p>
          </div>
        )}

        {/* Close */}
        <button
          onClick={onClose}
          className="w-full mt-6 bg-accent hover:bg-accent-hover text-black py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  );
}
