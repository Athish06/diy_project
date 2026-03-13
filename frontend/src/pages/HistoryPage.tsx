import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchScans, fetchScanById } from '@/lib/api';
import type { ScanHistoryItem, ScanFull } from '@/lib/api';
import VideoInfo from '@/components/VideoInfo';
import DiyStepsContainer from '@/components/DiyStepsContainer';
import ModelResultsTabs from '@/components/ModelResultsTabs';
import RightPanel from '@/components/RightPanel';
import type {
  DiyStep,
  DiyExtraction,
  SafetyReport,
  VideoMetadata,
  ComplianceVerdict,
  StepSafetyAnalysis,
  ModelReport,
  ModelComparison,
} from '@/types';

/* -------------------------------------------------------------------------- */
/* Verdict badge config                                                       */
/* -------------------------------------------------------------------------- */
const VERDICT_CFG: Record<ComplianceVerdict, { label: string; bg: string; fg: string }> = {
  SAFE: { label: 'Safe', bg: '#e6f9f0', fg: '#0d9f5e' },
  UNSAFE: { label: 'Unsafe', bg: '#fde8e8', fg: '#d93025' },
  PROFESSIONAL_REQUIRED: { label: 'Caution', bg: '#fff4e6', fg: '#e67700' },
};

/* -------------------------------------------------------------------------- */
/* Main component                                                             */
/* -------------------------------------------------------------------------- */
export default function HistoryPage() {
  const navigate = useNavigate();
  const [scans, setScans] = useState<ScanHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedScan, setSelectedScan] = useState<ScanFull | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [selectedStepNumber, setSelectedStepNumber] = useState<number | null>(null);

  useEffect(() => {
    fetchScans()
      .then(setScans)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleCardClick = useCallback(async (scan: ScanHistoryItem) => {
    setLoadingDetail(true);
    setSelectedStepNumber(null);
    try {
      const full = await fetchScanById(scan.id);
      setSelectedScan(full);
    } catch {
      /* ignore */
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const handleBack = useCallback(() => {
    setSelectedScan(null);
    setSelectedStepNumber(null);
  }, []);

  const handleStepSelect = useCallback((stepNumber: number) => {
    setSelectedStepNumber((prev) => (prev === stepNumber ? null : stepNumber));
  }, []);

  /* Derive data from selected scan (always computed, even if null) */
  const scanOut = selectedScan?.output_json ?? {};
  const scanMd = (scanOut.metadata ?? {}) as VideoMetadata;
  const scanSteps = (scanOut.steps ?? []) as DiyStep[];
  const scanExtraction = (scanOut.extraction ?? null) as DiyExtraction | null;
  const scanReport = (scanOut.report ?? null) as SafetyReport | null;
  const scanModelReports = ((scanOut as any).modelReports ?? {}) as Record<string, ModelReport>;
  const scanComparison = ((scanOut as any).comparison ?? null) as ModelComparison | null;

  const selectedStepAnalysis: StepSafetyAnalysis | null = useMemo(() => {
    if (!scanReport || selectedStepNumber === null) return null;
    return scanReport.step_safety_analysis.find((s) => s.step_number === selectedStepNumber) ?? null;
  }, [scanReport, selectedStepNumber]);
  /* ---------------------------------------------------------------------- */
  /* Detail view — reuses the exact same components as the main App page     */
  /* ---------------------------------------------------------------------- */
  if (selectedScan) {
    return (
      <div className="app-shell">
        {/* Top bar matching main page style */}
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-brand">DIY Safety</span>
            <div className="topbar-sep" />
            <button onClick={handleBack} className="topbar-btn" title="Back to History">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              History
            </button>
          </div>
          <div className="topbar-right">
            <button onClick={() => navigate('/')} className="topbar-btn" title="New Analysis">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              New
            </button>
          </div>
        </header>

        {/* Same layout structure as main page: center-panel + right-panel */}
        <div className="app-layout">
          <main className="center-panel">
            <VideoInfo
              title={scanMd.title || selectedScan.title}
              channel={(scanMd as any).author || selectedScan.channel || ''}
              videoId={scanMd.id || selectedScan.video_id}
            />

            <DiyStepsContainer
              steps={scanSteps}
              extraction={scanExtraction}
              report={scanReport}
              isAnalyzing={false}
              selectedStep={selectedStepNumber}
              onStepSelect={handleStepSelect}
              hideReportSection={Object.keys(scanModelReports).length > 0}
            />

            {Object.keys(scanModelReports).length > 0 && (
              <ModelResultsTabs
                modelReports={scanModelReports}
                comparison={scanComparison}
                steps={scanSteps}
                isAnalyzing={false}
                selectedStep={selectedStepNumber}
                onStepSelect={handleStepSelect}
              />
            )}
          </main>

          <RightPanel
            report={scanReport}
            selectedStep={selectedStepAnalysis}
            isAnalyzing={false}
          />
        </div>
      </div>
    );
  }

  /* ---------------------------------------------------------------------- */
  /* Cards grid view                                                         */
  /* ---------------------------------------------------------------------- */
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-brand">DIY Safety</span>
          <div className="topbar-sep" />
          <button onClick={() => navigate('/')} className="topbar-btn" title="Home">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
            Home
          </button>
        </div>
      </header>

      <div className="history-container">
        <div className="history-header">
          <h1 className="history-title">Scan History</h1>
          <p className="history-subtitle">{scans.length} completed scan{scans.length !== 1 ? 's' : ''}</p>
        </div>

        {loading ? (
          <div className="history-loading">
            <div className="analyzing-spinner" />
            <p>Loading scan history…</p>
          </div>
        ) : scans.length === 0 ? (
          <div className="history-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.3 }}>
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
            <p>No scans yet. Analyze a YouTube video to get started.</p>
            <button onClick={() => navigate('/')} className="history-cta-btn">Go to Analyzer</button>
          </div>
        ) : (
          <div className="history-grid">
            {scans.map((scan) => {
              const v = VERDICT_CFG[(scan.verdict ?? 'SAFE') as ComplianceVerdict] ?? VERDICT_CFG.SAFE;
              const confidence = Math.round(100 - ((scan.risk_score ?? 0) / 5) * 100);
              return (
                <button
                  key={scan.id}
                  onClick={() => handleCardClick(scan)}
                  className="history-card"
                >
                  <img
                    src={`https://img.youtube.com/vi/${scan.video_id}/mqdefault.jpg`}
                    alt=""
                    className="history-card-thumb"
                    loading="lazy"
                  />
                  <div className="history-card-body">
                    <h3 className="history-card-title">{scan.title}</h3>
                    <p className="history-card-channel">{scan.channel}</p>
                    <div className="history-card-footer">
                      <span className="history-verdict-badge" style={{ background: v.bg, color: v.fg }}>{v.label}</span>
                      <span className="history-card-conf">{confidence}%</span>
                      <span className="history-card-date">
                        {scan.scan_timestamp ? new Date(scan.scan_timestamp).toLocaleDateString() : ''}
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {loadingDetail && (
        <div className="history-overlay">
          <div className="analyzing-spinner" />
        </div>
      )}
    </div>
  );
}
