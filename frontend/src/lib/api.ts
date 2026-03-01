import type {
  SafetyExtractionResult,
  DbRulesResponse,
  FilterOptions,
  DocumentCard,
  ExtractionRun,
  MultiExtractionResponse,
  EvaluationResults,
} from '@/types/safety';

const _raw = import.meta.env.VITE_API_URL as string | undefined;   // e.g. "http://localhost:8000"
const BACKEND_URL = _raw?.replace(/\/+$/, '') ?? '';                // strip trailing slash
const API_BASE = BACKEND_URL ? `${BACKEND_URL}/api` : '/api';      // absolute or relative

/** Check backend health and configuration status. */
export async function checkHealth(): Promise<{
  status: string;
  api_key_configured: boolean;
  database_configured: boolean;
  model: string;
}> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error('Backend not reachable');
  return res.json();
}

/**
 * Upload multiple PDF files for safety rule extraction.
 * Each file goes through the full pipeline with evaluation.
 */
export async function extractRulesMulti(files: File[]): Promise<MultiExtractionResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  const res = await fetch(`${API_BASE}/extract_rules`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Extraction failed');
  }
  return res.json();
}

/**
 * Upload a single PDF file for safety rule extraction.
 * Kept for backward compatibility.
 */
export async function extractRules(file: File): Promise<SafetyExtractionResult> {
  const formData = new FormData();
  formData.append('files', file);
  const res = await fetch(`${API_BASE}/extract_rules`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Extraction failed');
  }
  const data: MultiExtractionResponse = await res.json();
  if (data.results.length > 0) {
    return data.results[0].extraction;
  }
  throw new Error(data.errors[0]?.error || 'No results');
}

/**
 * Fetch existing rules from the database with optional filters & pagination.
 */
export async function fetchRules(params: {
  category?: string;
  severity?: number;
  document?: string;
  search?: string;
  run_id?: number;
  page?: number;
  perPage?: number;
}): Promise<DbRulesResponse> {
  const sp = new URLSearchParams();
  if (params.category) sp.set('category', params.category);
  if (params.severity != null) sp.set('severity', String(params.severity));
  if (params.document) sp.set('document', params.document);
  if (params.search) sp.set('search', params.search);
  if (params.run_id != null) sp.set('run_id', String(params.run_id));
  if (params.page != null) sp.set('page', String(params.page));
  if (params.perPage != null) sp.set('per_page', String(params.perPage));

  const res = await fetch(`${API_BASE}/rules?${sp.toString()}`);
  if (!res.ok) {
    return { rules: [], total: 0, page: 1, per_page: 50 };
  }
  return res.json();
}

/**
 * Fetch filter options (distinct categories, severities, documents) from DB.
 */
export async function fetchFilterOptions(): Promise<FilterOptions> {
  const res = await fetch(`${API_BASE}/filter_options`);
  if (!res.ok) {
    return { categories: [], severities: [], documents: [] };
  }
  return res.json();
}

/**
 * Fetch rules grouped by source_document for PDF card view.
 */
export async function fetchRulesByDocument(): Promise<{ documents: DocumentCard[] }> {
  const res = await fetch(`${API_BASE}/rules_by_document`);
  if (!res.ok) {
    return { documents: [] };
  }
  return res.json();
}

/**
 * Fetch all extraction runs with evaluation results.
 */
export async function fetchExtractionRuns(): Promise<{ runs: ExtractionRun[] }> {
  const res = await fetch(`${API_BASE}/extraction_runs`);
  if (!res.ok) {
    return { runs: [] };
  }
  return res.json();
}

/**
 * Trigger brutal evaluation on an existing run.
 */
export async function runEvaluation(runId: number): Promise<{ run_id: number; evaluation_results: EvaluationResults }> {
  const res = await fetch(`${API_BASE}/run_evaluation/${runId}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Evaluation failed');
  }
  return res.json();
}


/**
 * Extract rules via WebSocket with real-time progress.
 * Returns a cleanup function to close the connection.
 */
export function extractRulesWithProgress(
  files: File[],
  onProgress: (event: import('@/types/safety').ExtractionProgressEvent) => void,
  onComplete: () => void,
  onError: (error: string) => void,
): { close: () => void } {
  // Derive WS url from VITE_API_URL  (http→ws, https→wss)
  let wsBase: string;
  if (BACKEND_URL) {
    wsBase = BACKEND_URL.replace(/^http/, 'ws');
  } else {
    const wsProt = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsBase = `${wsProt}//${window.location.host}`;
  }
  const wsUrl = `${wsBase}/ws/extract`;
  const ws = new WebSocket(wsUrl);

  let closed = false;

  ws.onopen = async () => {
    try {
      // Convert files to base64
      const fileData: Array<{ name: string; data: string }> = [];
      for (const file of files) {
        const buffer = await file.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const b64 = btoa(binary);
        fileData.push({ name: file.name, data: b64 });
      }

      ws.send(JSON.stringify({ files: fileData }));
    } catch (err) {
      onError(`Failed to send files: ${err}`);
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onProgress(data);

      if (data.step === 'done') {
        onComplete();
      } else if (data.step === 'error') {
        onError(data.status || 'Unknown error');
      }
    } catch {
      // ignore parse errors
    }
  };

  ws.onerror = () => {
    if (!closed) onError('WebSocket connection failed');
  };

  ws.onclose = () => {
    closed = true;
  };

  return {
    close: () => {
      closed = true;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Completed Scans (persistent history)
// ---------------------------------------------------------------------------

export interface ScanHistoryItem {
  id: number;
  video_id: string;
  video_url: string;
  title: string;
  channel: string | null;
  verdict: string | null;
  risk_score: number | null;
  scan_timestamp: string | null;
}

export interface ScanFull extends ScanHistoryItem {
  output_json: {
    steps?: unknown[];
    extraction?: unknown;
    report?: unknown;
    metadata?: unknown;
  };
}

/** Save a completed scan to the database. */
export async function saveScan(data: {
  video_id: string;
  video_url: string;
  title: string;
  channel: string;
  verdict: string;
  risk_score: number;
  output_json: Record<string, unknown>;
}): Promise<{ id: number; scan_timestamp: string }> {
  const res = await fetch(`${API_BASE}/scans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to save scan');
  return res.json();
}

/** Fetch recent scan history (latest 50). */
export async function fetchScans(): Promise<ScanHistoryItem[]> {
  const res = await fetch(`${API_BASE}/scans`);
  if (!res.ok) throw new Error('Failed to load scan history');
  const json = await res.json();
  return json.scans;
}

/** Fetch a single scan with its full output. */
export async function fetchScanById(scanId: number): Promise<ScanFull> {
  const res = await fetch(`${API_BASE}/scans/${scanId}`);
  if (!res.ok) throw new Error('Scan not found');
  return res.json();
}
