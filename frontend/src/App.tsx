import { useState, useCallback, lazy, Suspense } from 'react';
import Header from '@/components/Header';
import DiyForm from '@/components/DiyForm';
import VideoInfo from '@/components/VideoInfo';
import DiyStepsContainer from '@/components/DiyStepsContainer';
import AnalysisProgress from '@/components/AnalysisProgress';
import { useDiyAnalysis } from '@/hooks/useDiyAnalysis';

const ParticleCanvas = lazy(() => import('@/components/ParticleCanvas'));
const SettingsPanel = lazy(() => import('@/components/SettingsPanel'));

export default function App() {
  const [showSettings, setShowSettings] = useState(false);

  const {
    steps,
    extraction,
    report,
    rawText,
    isLoading,
    isAnalyzing,
    error,
    metadata,
    statusMessage,
    phase,
    elapsedMs,
    isNotDiy,
    submitUrl,
    dismissError,
  } = useDiyAnalysis();

  const handleSubmit = useCallback((url: string) => {
    submitUrl(url);
  }, [submitUrl]);

  return (
    <div className="relative flex flex-col min-h-screen max-w-2xl mx-auto">
      <Suspense fallback={null}>
        <ParticleCanvas />
      </Suspense>
      <Header onOpenSettings={() => setShowSettings(true)} />

      <main className="flex-1 px-6 pb-6 space-y-4">
        <DiyForm
          onSubmit={handleSubmit}
          disabled={isLoading}
          isLoading={isLoading}
        />

        {/* Dismissible error */}
        {error ? (
          <div className="error-banner glass-card animate-fade-in">
            <div className="flex items-start gap-3">
              <svg className="shrink-0 mt-0.5 text-red-400" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              <p className="flex-1 text-sm text-red-400">{error}</p>
              <button onClick={dismissError} className="shrink-0 text-red-400/60 hover:text-red-400 transition-colors" aria-label="Dismiss">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
        ) : null}

        {/* Phase progress stepper */}
        {isLoading && (
          <AnalysisProgress
            phase={phase}
            elapsedMs={elapsedMs}
            statusMessage={statusMessage}
          />
        )}

        <VideoInfo
          title={metadata?.title}
          channel={metadata?.author}
          videoId={metadata?.id}
        />

        {/* Streaming text preview */}
        {isLoading && steps.length === 0 && rawText ? (
          <div className="streaming-card glass-card animate-fade-in">
            <div className="streaming-card-header">
              <div className="streaming-dots">
                <span /><span /><span />
              </div>
              <span className="text-xs text-muted">Live extraction stream</span>
            </div>
            <pre className="streaming-content">
              {rawText.slice(-600)}
              <span className="streaming-cursor" />
            </pre>
          </div>
        ) : null}

        {/* Not DIY banner */}
        {isNotDiy && metadata ? (
          <div className="glass-card px-5 py-6 text-center animate-fade-in">
            <div className="text-3xl mb-2">🎬</div>
            <h2 className="text-lg font-semibold mb-1">Not a DIY Video</h2>
            <p className="text-sm text-muted">
              &ldquo;{metadata.title}&rdquo; does not appear to be a DIY tutorial.
              Safety analysis is only available for DIY content.
            </p>
          </div>
        ) : null}

        <DiyStepsContainer
          steps={steps}
          extraction={extraction}
          report={report}
          isAnalyzing={isAnalyzing}
        />
      </main>

      <Suspense fallback={null}>
        {showSettings ? (
          <SettingsPanel onClose={() => setShowSettings(false)} />
        ) : null}
      </Suspense>
    </div>
  );
}
