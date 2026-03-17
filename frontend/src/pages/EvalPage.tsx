import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  collectSystemEvalUrls,
  fetchLatestSystemEvaluation,
  fetchSystemEvalUrlPool,
  runSystemEvaluation,
} from '@/lib/api';
import type { SystemEvalResult } from '@/types/safety';

function MetricBar({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="eval-metric-row">
      <div className="eval-metric-row-head">
        <span>{label}</span>
        <span>{Number.isFinite(value) ? value.toFixed(2) : 'N/A'}</span>
      </div>
      <div className="eval-bar-track">
        <div className="eval-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function EvalPage() {
  const navigate = useNavigate();
  const [result, setResult] = useState<SystemEvalResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sampleSize, setSampleSize] = useState(50);
  const [pastedUrls, setPastedUrls] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [totalUrlsInPool, setTotalUrlsInPool] = useState(0);
  const [randomMin, setRandomMin] = useState(1);
  const [randomMax, setRandomMax] = useState(10);

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const latest = await fetchLatestSystemEvaluation();
      setResult(latest);
      const pool = await fetchSystemEvalUrlPool();
      setTotalUrlsInPool(pool.total_urls);
      if (pool.total_urls > 0) {
        setRandomMin(1);
        setRandomMax(Math.min(10, pool.total_urls));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
  }, [loadLatest]);

  const runEvaluation = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const next = await runSystemEvaluation({
        sampleSize,
        randomMin,
        randomMax,
        usePool: true,
      });
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [sampleSize, randomMin, randomMax]);

  const collectUrls = useCallback(async () => {
    setCollecting(true);
    setError(null);
    try {
      const data = await collectSystemEvalUrls({ files, pastedUrls });
      setPastedUrls('');
      setFiles([]);
      setTotalUrlsInPool(data.total_urls_in_pool);
      if (data.total_urls_in_pool > 0) {
        setRandomMin(1);
        setRandomMax(Math.min(Math.max(1, randomMax), data.total_urls_in_pool));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCollecting(false);
    }
  }, [files, pastedUrls, randomMax]);

  const scanBreakdown = result?.details?.scan_breakdown ?? [];

  const confusionTotal = useMemo(() => {
    if (!result) return 0;
    const c = result.confusion_matrix;
    return c.true_positive + c.true_negative + c.false_positive + c.false_negative;
  }, [result]);

  const latestMetrics = result?.metrics;
  const cumulativeMetrics = result?.cumulative?.metrics;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-brand">DIY Safety</span>
          <div className="topbar-sep" />
          <button onClick={() => navigate('/')} className="topbar-btn" title="Home">Home</button>
        </div>
      </header>

      <div className="eval-container">
        <div className="eval-header">
          <div>
            <h1 className="eval-title">System Evaluation</h1>
            <p className="eval-subtitle">Detailed quality metrics over recent scans (latest result only).</p>
          </div>
          <div className="eval-controls">
            <input
              type="number"
              min={1}
              max={500}
              value={sampleSize}
              onChange={(e) => setSampleSize(Math.max(1, Math.min(500, Number(e.target.value) || 50)))}
              className="safety-input"
              style={{ width: 120 }}
            />
            <input
              type="number"
              min={1}
              max={Math.max(1, totalUrlsInPool)}
              value={randomMin}
              onChange={(e) => setRandomMin(Math.max(1, Math.min(Number(e.target.value) || 1, Math.max(1, totalUrlsInPool))))}
              className="safety-input"
              style={{ width: 90 }}
              title="Random min"
            />
            <input
              type="number"
              min={randomMin}
              max={Math.max(randomMin, totalUrlsInPool)}
              value={randomMax}
              onChange={(e) => setRandomMax(Math.max(randomMin, Math.min(Number(e.target.value) || randomMin, Math.max(randomMin, totalUrlsInPool))))}
              className="safety-input"
              style={{ width: 90 }}
              title="Random max"
            />
            <button onClick={runEvaluation} className="history-cta-btn" disabled={running}>
              {running ? 'Running Evaluation...' : 'Run Fresh Evaluation'}
            </button>
          </div>
        </div>

        <section className="glass-card eval-card" style={{ marginBottom: 14 }}>
          <h3 className="eval-card-title">URL Sources</h3>
          <p className="eval-meta">Upload PDF or Excel (column: url or youtube_url, case-insensitive), or paste comma-separated YouTube URLs.</p>
          <div className="eval-controls" style={{ marginTop: 10, flexWrap: 'wrap' }}>
            <input
              type="file"
              multiple
              accept=".pdf,.xlsx,.xls,.csv,.txt"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="safety-input"
              style={{ minWidth: 280 }}
            />
            <button onClick={collectUrls} className="history-cta-btn" disabled={collecting}>
              {collecting ? 'Collecting...' : 'Collect URLs'}
            </button>
          </div>
          <textarea
            value={pastedUrls}
            onChange={(e) => setPastedUrls(e.target.value)}
            placeholder="Paste YouTube URLs separated by commas"
            className="safety-input"
            style={{ width: '100%', minHeight: 84, marginTop: 10 }}
          />
          <div className="eval-meta" style={{ marginTop: 8 }}>
            Total URLs in bucket: <strong>{totalUrlsInPool}</strong> | Random scan range: <strong>{randomMin}</strong> to <strong>{randomMax}</strong>
          </div>
        </section>

        {loading ? (
          <div className="history-loading"><div className="analyzing-spinner" /><p>Loading latest evaluation...</p></div>
        ) : error ? (
          <div className="glass-card" style={{ padding: 16, borderColor: 'rgba(239,68,68,0.35)' }}>
            <p style={{ color: 'var(--color-unsafe)' }}>{error}</p>
          </div>
        ) : !result ? (
          <div className="history-empty">
            <p>No system evaluation result yet.</p>
            <button onClick={runEvaluation} className="history-cta-btn" disabled={running}>
              {running ? 'Running Evaluation...' : 'Run First Evaluation'}
            </button>
          </div>
        ) : (
          <div className="eval-grid">
            <section className="glass-card eval-card">
              <h3 className="eval-card-title">Latest Run</h3>
              <p className="eval-meta">Evaluated At: {new Date(result.evaluated_at).toLocaleString()}</p>
              <p className="eval-meta">Model: {result.model_key}</p>
              <p className="eval-meta">Configured Sample Size: {result.sample_size}</p>
              <p className="eval-meta">Total URLs In Pool: {result.total_urls_in_pool ?? totalUrlsInPool}</p>
              <p className="eval-meta">URLs Selected This Run: {result.selected_urls_count ?? result.youtube_urls?.length ?? 0}</p>
              <p className="eval-meta">Scans Evaluated: {result.evaluated_scans}</p>
              <p className="eval-meta">Steps Evaluated: {result.total_steps}</p>
              <p className="eval-meta">Precautions Supported: {result.supported_precautions}/{result.total_precautions}</p>
            </section>

            <section className="glass-card eval-card">
              <h3 className="eval-card-title">Core Metrics</h3>
              <MetricBar label="Accuracy" value={result.metrics.accuracy} />
              <MetricBar label="Precision" value={result.metrics.precision} />
              <MetricBar label="Recall" value={result.metrics.recall} />
              <MetricBar label="F1 Score" value={result.metrics.f1_score} />
            </section>

            <section className="glass-card eval-card">
              <h3 className="eval-card-title">Ranking And Faithfulness</h3>
              <MetricBar label="Mean Reciprocal Rank (MRR)" value={result.metrics.mean_reciprocal_rank} max={1} />
              <MetricBar label="Faithfulness Score" value={result.metrics.faithfulness_score} />
              <div className="eval-spearman-box">
                <span>Spearman Correlation</span>
                <strong>{result.metrics.spearman_correlation == null ? 'N/A' : result.metrics.spearman_correlation.toFixed(4)}</strong>
              </div>
            </section>

            <section className="glass-card eval-card eval-span-2">
              <h3 className="eval-card-title">Confusion Matrix</h3>
              <div className="eval-confusion-grid">
                <div className="eval-conf-cell"><span>TP</span><strong>{result.confusion_matrix.true_positive}</strong></div>
                <div className="eval-conf-cell"><span>FP</span><strong>{result.confusion_matrix.false_positive}</strong></div>
                <div className="eval-conf-cell"><span>FN</span><strong>{result.confusion_matrix.false_negative}</strong></div>
                <div className="eval-conf-cell"><span>TN</span><strong>{result.confusion_matrix.true_negative}</strong></div>
              </div>
              <p className="eval-meta" style={{ marginTop: 10 }}>Total classified steps: {confusionTotal}</p>
            </section>

            <section className="glass-card eval-card eval-span-2">
              <h3 className="eval-card-title">Latest Vs Cumulative</h3>
              {!latestMetrics || !cumulativeMetrics ? (
                <p className="eval-meta">Cumulative graph will appear after at least one saved run.</p>
              ) : (
                <div className="eval-compare-grid">
                  {[
                    ['Accuracy', latestMetrics.accuracy, cumulativeMetrics.accuracy],
                    ['Precision', latestMetrics.precision, cumulativeMetrics.precision],
                    ['Recall', latestMetrics.recall, cumulativeMetrics.recall],
                    ['F1', latestMetrics.f1_score, cumulativeMetrics.f1_score],
                  ].map(([label, latest, cumulative]) => {
                    const latestPct = Math.max(0, Math.min(100, Number(latest)));
                    const cumPct = Math.max(0, Math.min(100, Number(cumulative)));
                    return (
                      <div key={String(label)} className="eval-compare-row">
                        <div className="eval-metric-row-head">
                          <span>{String(label)}</span>
                          <span>L {latestPct.toFixed(1)} | C {cumPct.toFixed(1)}</span>
                        </div>
                        <div className="eval-compare-track">
                          <div className="eval-compare-latest" style={{ width: `${latestPct}%` }} />
                          <div className="eval-compare-cumulative" style={{ width: `${cumPct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="glass-card eval-card eval-span-2">
              <h3 className="eval-card-title">Recent Scan Breakdown</h3>
              {scanBreakdown.length === 0 ? (
                <p className="eval-meta">No per-scan breakdown available.</p>
              ) : (
                <div className="eval-table-wrap">
                  <table className="safety-table">
                    <thead>
                      <tr>
                        <th>Scan</th>
                        <th>Steps</th>
                        <th>Avg LLM Risk</th>
                        <th>Avg Override Risk</th>
                        <th>Spearman</th>
                        <th>MRR</th>
                        <th>Faithfulness</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scanBreakdown.slice(0, 20).map((scan) => (
                        <tr key={scan.scan_id}>
                          <td className="max-w-[320px]">
                            <div className="line-clamp-1">{scan.title}</div>
                            <div className="text-xs text-muted">{scan.video_id}</div>
                          </td>
                          <td>{scan.steps_evaluated}</td>
                          <td>{scan.avg_llm_risk.toFixed(2)}</td>
                          <td>{scan.avg_override_risk.toFixed(2)}</td>
                          <td>{scan.scan_spearman == null ? 'N/A' : scan.scan_spearman.toFixed(3)}</td>
                          <td>{scan.scan_mrr.toFixed(3)}</td>
                          <td>{scan.faithfulness.toFixed(2)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
