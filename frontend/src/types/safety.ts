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
  run_id: number | null;
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

/** Document card for PDF-grouped view. */
export interface DocumentCard {
  name: string;
  rule_count: number;
  categories: string[];
  avg_severity: number;
  last_updated: string;
}

/** Per-check evaluation accuracy percentages (varies by evaluation type). */
export type PerCheckAccuracy = Record<string, number>;

/** Failed rule detail from evaluation. */
export interface EvalFailedRule {
  rule_id: string;
  actionable_rule: string;
  checks: Record<string, boolean>;
  all_passed: boolean;
  failed_checks: string[];
}

/** Evaluation results for an extraction run. */
export interface EvaluationResults {
  total_rules: number;
  total_checks: number;
  checks_passed: number;
  overall_accuracy: number;
  per_check_accuracy: PerCheckAccuracy;
  rules_all_passed: number;
  rules_with_failures: number;
  hallucination_rate?: number;
  correctness_score?: number;
  category_validity_pct?: number;
  severity_consistency_pct?: number;
  cosine_similarity_passed?: number;
  cosine_similarity_threshold?: number;
  rules_removed_for_text_presence?: number;
  failed_rules: EvalFailedRule[];
}

/** An extraction run record. */
export interface ExtractionRun {
  id: number;
  run_timestamp: string;
  model_used: string;
  total_pages: number;
  rule_count: number;
  document_count: number;
  source_documents: string[];
  json_source_file: string;
  file_url: string | null;
  evaluation_results: EvaluationResults | null;
  created_at: string;
}

/** Response from multi-file extraction. */
export interface ExtractionFileResult {
  file: string;
  run_id: number;
  extraction: SafetyExtractionResult;
  evaluation_results: EvaluationResults;
}

export interface MultiExtractionResponse {
  results: ExtractionFileResult[];
  errors: { file: string; error: string }[];
  total_files: number;
  successful: number;
  failed: number;
}

/** Severity metadata for display. */
export interface SeverityInfo {
  label: string;
  color: string;
  bgClass: string;
}

export const SEVERITY_MAP: Record<number, SeverityInfo> = {
  1: { label: 'Info', color: '#6ee7b7', bgClass: 'severity-1' },
  2: { label: 'Low', color: '#86efac', bgClass: 'severity-2' },
  3: { label: 'Medium', color: '#fcd34d', bgClass: 'severity-3' },
  4: { label: 'High', color: '#fb923c', bgClass: 'severity-4' },
  5: { label: 'Critical', color: '#f87171', bgClass: 'severity-5' },
};


/* ── WebSocket extraction progress ── */

export type ExtractionStep =
  | 'upload' | 'ingestion' | 'llm_extraction' | 'validation'
  | 'severity' | 'embedding' | 'dedup' | 'db_insert'
  | 'evaluation' | 'complete' | 'done' | 'error';

export interface ExtractionProgressEvent {
  step: ExtractionStep;
  status: string;
  file?: string;
  page?: number;
  total?: number;
  percentage?: number;
  rules_so_far?: number;
  rule_count?: number;
  before?: number;
  after?: number;
  removed?: number;
  run_id?: number;
  accuracy?: number;
  error?: string;
  results?: Array<{ run_id: number; rule_count: number; accuracy: number }>;
}
