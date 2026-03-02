import { useState, useCallback, useRef, useEffect } from 'react';
import type {
  VideoMetadata,
  DiyStep,
  DiyExtraction,
  SafetyReport,
  ModelReport,
  ModelComparison,
  AnalysisEvent,
  AnalysisPhase,
} from '@/types';
import { extractVideoId } from '@/utils/video';

export function useDiyAnalysis() {
  const [steps, setSteps] = useState<DiyStep[]>([]);
  const [extraction, setExtraction] = useState<DiyExtraction | null>(null);
  const [report, setReport] = useState<SafetyReport | null>(null);
  const [modelReports, setModelReports] = useState<Record<string, ModelReport>>({});
  const [comparison, setComparison] = useState<ModelComparison | null>(null);
  const [rawText, setRawText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<VideoMetadata | null>(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [phase, setPhase] = useState<AnalysisPhase>('idle');
  const [elapsedMs, setElapsedMs] = useState(0);
  const [isNotDiy, setIsNotDiy] = useState(false);
  const [safetyCategories, setSafetyCategories] = useState<string[]>([]);
  const rawTextRef = useRef('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Buffer incoming model reports; only commit to state when comparison arrives
  const pendingReportsRef = useRef<Record<string, ModelReport>>({});

  // Elapsed timer
  const startTimer = useCallback(() => {
    setElapsedMs(0);
    intervalRef.current = setInterval(() => {
      setElapsedMs((prev) => prev + 100);
    }, 100);
  }, []);

  const stopTimer = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopTimer();
      abortRef.current?.abort();
    };
  }, [stopTimer]);

  const dismissError = useCallback(() => setError(null), []);

  const handleEvent = useCallback((event: AnalysisEvent, videoId: string) => {
    switch (event.type) {
      case 'metadata':
        setMetadata({
          id: videoId,
          title: event.title,
          author: event.author,
        });
        break;

      case 'status':
        setStatusMessage(event.message);
        if (event.message.toLowerCase().includes('fetching')) {
          setPhase('fetching');
        } else if (event.message.toLowerCase().includes('extracting')) {
          setPhase('extracting');
        } else if (event.message.toLowerCase().includes('safety') || event.message.toLowerCase().includes('compliance')) {
          setPhase('analyzing');
          setIsAnalyzing(true);
        }
        break;

      case 'steps_delta': {
        // Strip <think>...</think> tokens from streaming preview
        let text = event.text;
        text = text.replace(/<\/?think>/g, '');
        if (text) {
          rawTextRef.current += text;
          setRawText(rawTextRef.current);
        }
        setPhase('extracting');
        break;
      }

      case 'steps_complete':
        try {
          const parsed = JSON.parse(event.steps_json);
          if (Array.isArray(parsed)) {
            setSteps(parsed as DiyStep[]);
          } else if (parsed && typeof parsed === 'object' && Array.isArray(parsed.steps)) {
            setExtraction(parsed as DiyExtraction);
            setSteps(parsed.steps as DiyStep[]);
          } else {
            setError('Unexpected extraction format.');
          }
          // Track is_diy and safety categories from the event
          if ('is_diy' in event) {
            setIsNotDiy(!event.is_diy);
          }
          if ('safety_categories' in event && Array.isArray(event.safety_categories)) {
            setSafetyCategories(event.safety_categories);
          }
          setPhase('analyzing');
          setStatusMessage('Steps extracted. Running safety analysis...');
        } catch {
          setError('Failed to parse extracted steps.');
        }
        break;

      case 'not_diy':
        setIsNotDiy(true);
        setIsLoading(false);
        setIsAnalyzing(false);
        setPhase('not_diy');
        setStatusMessage('');
        break;

      case 'safety_report':
        // Buffer without touching state — we commit everything atomically on model_comparison
        try {
          const parsed = JSON.parse(event.report_json) as SafetyReport;
          pendingReportsRef.current[event.model_key] = {
            key: event.model_key,
            label: event.model_label,
            report: parsed,
          };
        } catch {
          // ignore parse error
        }
        break;

      case 'model_comparison':
        // Both models are done — commit all buffered reports + comparison at once
        try {
          const parsedComparison = JSON.parse(event.comparison_json) as ModelComparison;
          const buffered = { ...pendingReportsRef.current };
          setModelReports(buffered);
          setComparison(parsedComparison);
          // Set primary report to qwen first, fallback to first available
          const primaryKey = ['qwen', 'gpt_oss'].find((k) => k in buffered);
          if (primaryKey) {
            setReport(buffered[primaryKey].report);
          }
          setIsAnalyzing(false);
          setStatusMessage('');
        } catch {
          setIsAnalyzing(false);
        }
        break;

      case 'done':
        setIsLoading(false);
        setIsAnalyzing(false);
        setPhase('complete');
        setStatusMessage('');
        break;

      case 'error':
        setError(event.message);
        setIsLoading(false);
        setIsAnalyzing(false);
        setPhase('error');
        setStatusMessage('');
        break;
    }
  }, []);

  const submitUrl = useCallback(async (url: string) => {
    const videoId = extractVideoId(url);
    if (!videoId) {
      setError('Invalid YouTube URL. Please enter a valid video link.');
      return;
    }

    // Abort any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Reset state
    setSteps([]);
    setExtraction(null);
    setReport(null);
    setModelReports({});
    setComparison(null);
    setRawText('');
    pendingReportsRef.current = {};
    rawTextRef.current = '';
    setError(null);
    setMetadata(null);
    setStatusMessage('Starting analysis...');
    setPhase('fetching');
    setIsLoading(true);
    setIsAnalyzing(false);
    setIsNotDiy(false);
    setSafetyCategories([]);
    startTimer();

    try {
      const apiBase = (import.meta.env.VITE_API_URL?.replace(/\/+$/, '') ?? '') + '/api';
      const res = await fetch(`${apiBase}/analyze?video_id=${encodeURIComponent(videoId)}`, {
        signal: controller.signal,
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `Analysis failed (${res.status})`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE events are separated by blank lines (\r\n\r\n or \n\n)
        // Normalize \r\n to \n so splitting works consistently
        buffer = buffer.replace(/\r\n/g, '\n');
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const lines = part.split('\n');
          let eventData = '';
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              eventData += line.slice(6);
            }
          }
          if (eventData) {
            try {
              const event = JSON.parse(eventData) as AnalysisEvent;
              handleEvent(event, videoId);
            } catch {
              // skip malformed SSE
            }
          }
        }
      }

      // Final: if we didn't get a 'done' event, mark complete
      setIsLoading(false);
      setIsAnalyzing(false);
      if (phase !== 'error') {
        setPhase('complete');
      }
      setStatusMessage('');
      stopTimer();
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setIsLoading(false);
      setIsAnalyzing(false);
      setPhase('error');
      setStatusMessage('');
      stopTimer();
    }
  }, [startTimer, stopTimer, handleEvent, phase]);

  const restoreState = useCallback((savedData: any) => {
    // Cancel any ongoing fetch
    abortRef.current?.abort();
    stopTimer();

    // Restore data from DB
    setSteps(savedData.steps || []);
    setExtraction(savedData.extraction || null);
    setReport(savedData.report || null);
    setMetadata(savedData.metadata || null);
    setModelReports(savedData.modelReports || {});
    setComparison(savedData.comparison || null);
    pendingReportsRef.current = {};

    // Reset UI state to "done"
    setPhase('complete');
    setIsLoading(false);
    setIsAnalyzing(false);
    setError(null);
    setStatusMessage('');
    setIsNotDiy(false);
    setRawText('');
    rawTextRef.current = '';
    setElapsedMs(0);
  }, [stopTimer]);

  return {
    steps,
    extraction,
    report,
    modelReports,
    comparison,
    rawText,
    isLoading,
    isAnalyzing,
    error,
    metadata,
    statusMessage,
    phase,
    elapsedMs,
    isNotDiy,
    safetyCategories,
    submitUrl,
    restoreState,
    dismissError,
  };
}
