/** A single atomic safety rule extracted by the pipeline. */
export interface SafetyRule {
  id: string;
  rule_text: string;
  category: string;
  severity: number;               // 1-5
  source_document: string;
  page_number: number;
  section_heading: string;
  source_quote: string;
  actionable: boolean;
  applies_to: string[];
}

/** Top-level JSON envelope returned by the extraction pipeline. */
export interface SafetyExtractionResult {
  extraction_timestamp: string;
  model_used: string;
  document_name: string;
  total_pages: number;
  rule_count: number;
  source_documents?: string[];
  document_count?: number;
  rules: SafetyRule[];
}

/** A rule row from the database (schema differs from extraction output). */
export interface DbSafetyRule {
  id: number;
  rule_id: string;
  original_text: string;
  actionable_rule: string;
  materials: string[];
  suggested_severity: number | null;
  validated_severity: number | null;
  categories: string[];
  source_document: string;
  page_number: number | null;
  section_heading: string;
  created_at: string;
}

/** Response from fetch_rules (paginated). */
export interface DbRulesResponse {
  rules: DbSafetyRule[];
  total: number;
  page: number;
  per_page: number;
}

/** Filter options available (distinct values from DB). */
export interface FilterOptions {
  categories: string[];
  severities: number[];
  documents: string[];
}

/** Severity metadata for display. */
export interface SeverityInfo {
  label: string;
  color: string;
  bgClass: string;
}

export const SEVERITY_MAP: Record<number, SeverityInfo> = {
  1: { label: 'Info',       color: '#6ee7b7', bgClass: 'severity-1' },
  2: { label: 'Low',        color: '#86efac', bgClass: 'severity-2' },
  3: { label: 'Medium',     color: '#fcd34d', bgClass: 'severity-3' },
  4: { label: 'High',       color: '#fb923c', bgClass: 'severity-4' },
  5: { label: 'Critical',   color: '#f87171', bgClass: 'severity-5' },
};
