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

export interface SystemEvalScanBreakdown {
  scan_id: number;
  video_id: string;
  title: string;
  scan_timestamp: string | null;
  steps_evaluated: number;
  avg_llm_risk: number;
  avg_override_risk: number;
  scan_spearman: number | null;
  scan_mrr: number;
  faithfulness: number;
}

export interface SystemEvalMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1_score: number;
  mean_reciprocal_rank: number;
  faithfulness_score: number;
  spearman_correlation: number | null;
}

export interface SystemEvalResult {
  id: number;
  evaluated_at: string;
  model_key: string;
  sample_size: number;
  youtube_urls?: string[];
  selected_urls_count?: number;
  total_urls_in_pool?: number;
  evaluated_scans: number;
  total_steps: number;
  total_precautions: number;
  supported_precautions: number;
  confusion_matrix: {
    true_positive: number;
    true_negative: number;
    false_positive: number;
    false_negative: number;
  };
  metrics: SystemEvalMetrics;
  details: {
    notes?: Record<string, string>;
    scan_breakdown?: SystemEvalScanBreakdown[];
    llm_override_pairs?: Array<{ llm: number; override: number }>;
  };
  cumulative?: {
    total_steps: number;
    total_precautions: number;
    supported_precautions: number;
    confusion_matrix: {
      true_positive: number;
      true_negative: number;
      false_positive: number;
      false_negative: number;
    };
    metrics: {
      accuracy: number;
      precision: number;
      recall: number;
      f1_score: number;
    };
  };
}

export interface UrlPoolResponse {
  total_urls: number;
  urls: string[];
}

export interface UrlCollectResponse {
  added_urls: string[];
  added_count: number;
  total_urls_in_pool: number;
}
