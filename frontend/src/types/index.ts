// --- Verdict ---
export type ComplianceVerdict = 'SAFE' | 'UNSAFE' | 'PROFESSIONAL_REQUIRED';

// --- Analysis Phases ---
export type AnalysisPhase = 'idle' | 'fetching' | 'extracting' | 'analyzing' | 'complete' | 'error' | 'not_diy';

// --- Video ---
export interface VideoMetadata {
  id: string;
  title: string;
  author: string;
}

// --- DIY Steps (from Groq extraction) ---
export interface DiyStep {
  step_number: number;
  transcript_excerpt: string;
  step_text: string;
  action_summary: string;
}

// --- Full extraction result (top-level from Groq) ---
export interface DiyExtraction {
  title: string;
  is_diy: boolean;
  diy_categories: string[];
  safety_categories: string[];
  materials: string[];
  tools: string[];
  steps: DiyStep[];
  safety_precautions: string[];
  target_audience: string;
  supervision_mentioned: boolean;
  skill_level: string;
}

// --- Matched rule from pgvector similarity search ---
export interface MatchedRule {
  rule_text: string;
  severity: number;
  category: string;
  relevance: string;
}

// --- Per-step safety analysis from final LLM assessment ---
export interface StepSafetyAnalysis {
  step_number: number;
  action_summary: string;
  risk_level: number;
  required_precautions: string[];
  already_mentioned_precautions: string[];
  missing_precautions: string[];
  matched_rules: MatchedRule[];
}

// --- Full safety report from final LLM assessment ---
export interface SafetyReport {
  verdict: ComplianceVerdict;
  overall_risk_score: number;
  parent_monitoring_required: boolean;
  parent_monitoring_reason: string;
  summary: string;
  critical_concerns: string[];
  step_safety_analysis: StepSafetyAnalysis[];
  safety_measures_in_video: string[];
  recommended_additional_measures: string[];
}

// --- Analysis SSE events (from Python backend) ---
export type AnalysisEvent =
  | { type: 'metadata'; title: string; author: string }
  | { type: 'status'; message: string }
  | { type: 'steps_delta'; text: string }
  | { type: 'steps_complete'; steps_json: string; is_diy: boolean; safety_categories: string[] }
  | { type: 'not_diy'; message: string }
  | { type: 'safety_report'; report_json: string }
  | { type: 'done' }
  | { type: 'error'; message: string };
