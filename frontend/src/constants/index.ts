import type { ComplianceVerdict } from '@/types';

// Groq defaults
export const DEFAULT_MODEL = 'qwen/qwen3-32b';

// Verdict display configuration
export const VERDICT_CONFIG: Record<ComplianceVerdict, { color: string; bgColor: string; label: string; icon: string; description: string }> = {
  SAFE: {
    color: '#6ee7b7',
    bgColor: 'rgba(110, 231, 183, 0.12)',
    label: 'Safe',
    icon: '✓',
    description: 'This procedure follows safety guidelines.',
  },
  UNSAFE: {
    color: '#f87171',
    bgColor: 'rgba(248, 113, 113, 0.12)',
    label: 'Unsafe',
    icon: '✕',
    description: 'Safety violations or missing precautions detected.',
  },
  PROFESSIONAL_REQUIRED: {
    color: '#fb923c',
    bgColor: 'rgba(251, 146, 60, 0.12)',
    label: 'Professional Required',
    icon: '⚠',
    description: 'This procedure requires a licensed professional.',
  },
};

// Severity level colors
export const SEVERITY_COLORS: Record<number, { color: string; label: string }> = {
  1: { color: '#6ee7b7', label: 'Info' },
  2: { color: '#86efac', label: 'Low' },
  3: { color: '#fcd34d', label: 'Medium' },
  4: { color: '#fb923c', label: 'High' },
  5: { color: '#f87171', label: 'Critical' },
};

// UI
export const COPY_FEEDBACK_DURATION_MS = 2000;

// Video ID validation
export const VIDEO_ID_LENGTH = 11;
export const VIDEO_ID_REGEX = new RegExp(`^[a-zA-Z0-9_-]{${VIDEO_ID_LENGTH}}$`);
