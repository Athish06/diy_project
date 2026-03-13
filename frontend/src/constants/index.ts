import type { ComplianceVerdict } from '@/types';

// Groq defaults
export const DEFAULT_MODEL = 'qwen/qwen3-32b';

// Verdict display configuration
export const VERDICT_CONFIG: Record<ComplianceVerdict, { color: string; bgColor: string; label: string; icon: string; description: string }> = {
  SAFE: {
    color: '#059669', // emerald-600
    bgColor: '#d1fae5', // emerald-100
    label: 'Safe',
    icon: '✓',
    description: 'This procedure follows safety guidelines.',
  },
  UNSAFE: {
    color: '#dc2626', // red-600
    bgColor: '#fee2e2', // red-100
    label: 'Unsafe',
    icon: '✕',
    description: 'Safety violations or missing precautions detected.',
  },
  PROFESSIONAL_REQUIRED: {
    color: '#ea580c', // orange-600
    bgColor: '#ffedd5', // orange-100
    label: 'Professional Required',
    icon: '⚠',
    description: 'This procedure requires a licensed professional.',
  },
};

// Severity level colors
export const SEVERITY_COLORS: Record<number, { color: string; label: string }> = {
  1: { color: '#059669', label: 'Info' },      // emerald-600
  2: { color: '#65a30d', label: 'Low' },       // lime-600
  3: { color: '#d97706', label: 'Medium' },    // amber-600
  4: { color: '#ea580c', label: 'High' },      // orange-600
  5: { color: '#dc2626', label: 'Critical' },  // red-600
};

// UI
export const COPY_FEEDBACK_DURATION_MS = 2000;

// Video ID validation
export const VIDEO_ID_LENGTH = 11;
export const VIDEO_ID_REGEX = new RegExp(`^[a-zA-Z0-9_-]{${VIDEO_ID_LENGTH}}$`);
