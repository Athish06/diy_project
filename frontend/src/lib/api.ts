import type { SafetyExtractionResult, DbRulesResponse, FilterOptions } from '@/types/safety';

const API_BASE = '/api';

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
 * Upload a PDF file for safety rule extraction.
 * Replaces the Tauri file-dialog + invoke pattern.
 */
export async function extractRules(file: File): Promise<SafetyExtractionResult> {
  const formData = new FormData();
  formData.append('file', file);
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
 * Fetch existing rules from the database with optional filters & pagination.
 */
export async function fetchRules(params: {
  category?: string;
  severity?: number;
  document?: string;
  search?: string;
  page?: number;
  perPage?: number;
}): Promise<DbRulesResponse> {
  const sp = new URLSearchParams();
  if (params.category) sp.set('category', params.category);
  if (params.severity != null) sp.set('severity', String(params.severity));
  if (params.document) sp.set('document', params.document);
  if (params.search) sp.set('search', params.search);
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
