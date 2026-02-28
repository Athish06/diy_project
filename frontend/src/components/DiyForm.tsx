import { useState, useCallback, type FormEvent } from 'react';

interface DiyFormProps {
  onSubmit: (url: string) => void;
  disabled: boolean;
  isLoading: boolean;
}

export default function DiyForm({ onSubmit, disabled, isLoading }: DiyFormProps) {
  const [url, setUrl] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim() || disabled || isLoading) return;
    onSubmit(url.trim());
  };

  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) setUrl(text.trim());
    } catch { /* clipboard not available */ }
  }, []);

  return (
    <form onSubmit={handleSubmit} className={`diy-form glass-card ${isLoading ? 'diy-form-loading' : ''}`}>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a YouTube DIY video URL..."
            disabled={isLoading}
            className="diy-form-input"
          />
          {!url && !isLoading && (
            <button
              type="button"
              onClick={handlePaste}
              className="diy-paste-btn"
              title="Paste from clipboard"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>Paste</span>
            </button>
          )}
        </div>
        <button
          type="submit"
          disabled={disabled || isLoading || !url.trim()}
          className="diy-submit-btn"
        >
          {isLoading ? (
            <>
              <svg className="diy-btn-spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10" strokeDasharray="31.4 31.4" strokeLinecap="round" /></svg>
              <span>Analyzing</span>
            </>
          ) : disabled ? (
            <span>Set up API key</span>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              <span>Analyze</span>
            </>
          )}
        </button>
      </div>
      {!disabled && !isLoading && (
        <p className="diy-form-hint">
          Supports youtube.com, youtu.be, and shorts links
        </p>
      )}
    </form>
  );
}
