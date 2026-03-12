import { useState, useCallback, useMemo, useEffect, lazy, Suspense } from 'react';
import TopBar from '@/components/TopBar';
import type { HistoryEntry } from '@/components/LeftSidebar';
import RightPanel from '@/components/RightPanel';
import DiyForm from '@/components/DiyForm';
import VideoInfo from '@/components/VideoInfo';
import DiyStepsContainer from '@/components/DiyStepsContainer';
import ModelResultsTabs from '@/components/ModelResultsTabs';
import AnalysisProgress from '@/components/AnalysisProgress';
import { useDiyAnalysis } from '@/hooks/useDiyAnalysis';
import { saveScan, fetchScans, fetchScanById } from '@/lib/api';
import type { StepSafetyAnalysis, DiyStep, DiyExtraction, SafetyReport, VideoMetadata } from '@/types';

const SettingsPanel = lazy(() => import('@/components/SettingsPanel'));

export default function App() {
  const [showSettings, setShowSettings] = useState(false);
  const [selectedStepNumber, setSelectedStepNumber] = useState<number | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [lastSavedVideoId, setLastSavedVideoId] = useState<string | null>(null);

  const {
    steps,
    extraction,
    report,
    modelReports,
    comparison,
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
    restoreState,
    dismissError,
  } = useDiyAnalysis();

  // Load history from DB on mount
  useEffect(() => {
    fetchScans()
      .then((scans) => {
        setHistory(
          scans.map((s) => ({
            scanId: s.id,
            id: `${s.video_id}-${s.id}`,
            videoId: s.video_id,
            title: s.title,
            channel: s.channel ?? '',
            verdict: (s.verdict ?? 'SAFE') as HistoryEntry['verdict'],
            riskScore: s.risk_score ?? 0,
            confidence: Math.round(100 - ((s.risk_score ?? 0) / 5) * 100),
            date: s.scan_timestamp
              ? new Date(s.scan_timestamp).toLocaleDateString()
              : '',
          }))
        );
      })
      .catch(() => { /* ignore */ });
  }, []);

  // Save to DB when analysis completes (phase=complete ensures all models finished)
  useEffect(() => {
    if (phase === 'complete' && report && metadata && metadata.id !== lastSavedVideoId) {
      setLastSavedVideoId(metadata.id);
      const videoUrl = `https://www.youtube.com/watch?v=${metadata.id}`;
      saveScan({
        video_id: metadata.id,
        video_url: videoUrl,
        title: metadata.title,
        channel: metadata.author,
        verdict: report.verdict,
        risk_score: report.overall_risk_score,
        output_json: {
          steps,
          extraction,
          report,
          metadata,
          modelReports,
          comparison,
        },
      })
        .then((res) => {
          const entry: HistoryEntry = {
            scanId: res.id,
            id: `${metadata.id}-${res.id}`,
            videoId: metadata.id,
            title: metadata.title,
            channel: metadata.author,
            verdict: report.verdict,
            riskScore: report.overall_risk_score,
            confidence: Math.round(100 - (report.overall_risk_score / 5) * 100),
            date: new Date().toLocaleDateString(),
          };
          setHistory((prev) => [entry, ...prev.filter((h) => h.videoId !== metadata.id)]);
        })
        .catch(() => { /* ignore save error */ });
    }
  }, [phase, report, metadata, modelReports, comparison]);

  const handleSubmit = useCallback((url: string) => {
    setSelectedStepNumber(null);
    submitUrl(url);
  }, [submitUrl]);

  const handleNewAnalysis = useCallback(() => {
    window.location.reload();
  }, []);

  const handleLoadHistory = useCallback(async (entry: HistoryEntry) => {
    try {
      const scan = await fetchScanById(entry.scanId);
      const out = scan.output_json;
      // Prevent the useEffect from re-saving this history item
      setLastSavedVideoId(entry.videoId);
      // Instantly restore saved state from DB
      restoreState(out);
    } catch {
      // Fallback: just re-analyze if DB fetch fails
      submitUrl(`https://www.youtube.com/watch?v=${entry.videoId}`);
    }
    setSelectedStepNumber(null);
  }, [restoreState, submitUrl]);

  const handleStepSelect = useCallback((stepNumber: number) => {
    setSelectedStepNumber((prev) => (prev === stepNumber ? null : stepNumber));
  }, []);

  const selectedStepAnalysis: StepSafetyAnalysis | null = useMemo(() => {
    if (!report || selectedStepNumber === null) return null;
    return report.step_safety_analysis.find((s) => s.step_number === selectedStepNumber) ?? null;
  }, [report, selectedStepNumber]);

  const handleExportJson = useCallback(() => {
    if (!steps.length) return;
    const data = { steps, extraction, safety_report: report, modelReports, comparison, metadata };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'diy-safety-report.json';
    a.click();
    URL.revokeObjectURL(url);
  }, [steps, extraction, report, modelReports, comparison, metadata]);

  const handleExportPdf = useCallback(() => {
    window.print();
  }, []);

  return (
    <div className="app-shell">
      {/* Global Top Bar */}
      <TopBar
        onExportJson={handleExportJson}
        onExportPdf={handleExportPdf}
        hasReport={!!report}
        onNewAnalysis={handleNewAnalysis}
        onOpenSettings={() => setShowSettings(true)}
      />

      <div className="app-layout">
        {/* Center Panel */}
        <main className="center-panel">
          <DiyForm
            onSubmit={handleSubmit}
            disabled={isLoading}
            isLoading={isLoading}
          />

          {/* Dismissible error */}
          {error ? (
            <div className="error-banner glass-card animate-fade-in">
              <div className="flex items-start gap-3">
                <svg className="shrink-0 mt-0.5 text-red-400" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                <p className="flex-1 text-sm text-red-400">{error}</p>
                <button onClick={dismissError} className="shrink-0 text-red-400/60 hover:text-red-400 transition-colors" aria-label="Dismiss">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
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
            selectedStep={selectedStepNumber}
            onStepSelect={handleStepSelect}
            hideReportSection={Object.keys(modelReports).length > 0 || isAnalyzing}
          />

          {/* Multi-model results section */}
          {(Object.keys(modelReports).length > 0 || (isAnalyzing && steps.length > 0)) && (
            <ModelResultsTabs
              modelReports={modelReports}
              comparison={comparison}
              steps={steps}
              isAnalyzing={isAnalyzing}
              selectedStep={selectedStepNumber}
              onStepSelect={handleStepSelect}
            />
          )}
        </main>

        {/* Right Panel */}
        <RightPanel
          report={report}
          selectedStep={selectedStepAnalysis}
          isAnalyzing={isAnalyzing}
        />
      </div>

      <Suspense fallback={null}>
        {showSettings ? (
          <SettingsPanel onClose={() => setShowSettings(false)} />
        ) : null}
      </Suspense>
    </div>
  );
}
