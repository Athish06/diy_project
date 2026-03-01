import { createContext, useContext, useState, useRef, useCallback, useEffect } from 'react';
import type { ExtractionProgressEvent, ExtractionStep } from '@/types/safety';
import { extractRulesWithProgress } from '@/lib/api';

interface ExtractionContextValue {
    extracting: boolean;
    progressEvents: ExtractionProgressEvent[];
    currentStep: ExtractionStep | null;
    extractError: string | null;
    startExtraction: (files: File[]) => void;
    dismissProgress: () => void;
}

const ExtractionContext = createContext<ExtractionContextValue | null>(null);

export function useExtraction(): ExtractionContextValue {
    const ctx = useContext(ExtractionContext);
    if (!ctx) throw new Error('useExtraction must be used within ExtractionProvider');
    return ctx;
}

export function ExtractionProvider({ children }: { children: React.ReactNode }) {
    const [extracting, setExtracting] = useState(false);
    const [progressEvents, setProgressEvents] = useState<ExtractionProgressEvent[]>([]);
    const [currentStep, setCurrentStep] = useState<ExtractionStep | null>(null);
    const [extractError, setExtractError] = useState<string | null>(null);
    const wsCloseRef = useRef<(() => void) | null>(null);

    // Callback refs for data refresh (set by SafetyPage when mounted)
    const onCompleteRef = useRef<(() => void) | null>(null);

    const startExtraction = useCallback((files: File[]) => {
        // Close previous connection if any
        wsCloseRef.current?.();

        setExtracting(true);
        setExtractError(null);
        setProgressEvents([]);
        setCurrentStep(null);

        const { close } = extractRulesWithProgress(
            files,
            (event) => {
                setProgressEvents((prev) => [...prev, event]);
                setCurrentStep(event.step);
            },
            () => {
                setExtracting(false);
                // Trigger refresh if SafetyPage is mounted
                onCompleteRef.current?.();
            },
            (error) => {
                setExtractError(error);
                setExtracting(false);
            },
        );
        wsCloseRef.current = close;
    }, []);

    const dismissProgress = useCallback(() => {
        setProgressEvents([]);
        setCurrentStep(null);
        setExtractError(null);
    }, []);

    // Cleanup on unmount
    useEffect(() => {
        return () => { wsCloseRef.current?.(); };
    }, []);

    return (
        <ExtractionContext.Provider
            value={{
                extracting,
                progressEvents,
                currentStep,
                extractError,
                startExtraction,
                dismissProgress,
            }}
        >
            {children}
        </ExtractionContext.Provider>
    );
}

// Export the onComplete ref setter for SafetyPage to use
export { ExtractionContext };
