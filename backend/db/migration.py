"""Database migration definitions.

Used by run_migration.py at the project root.
"""

MIGRATIONS = [
    # 1. Add run_id column to safety_rules
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'safety_rules' AND column_name = 'run_id'
        ) THEN
            ALTER TABLE safety_rules ADD COLUMN run_id INTEGER REFERENCES extraction_runs(id);
        END IF;
    END $$;
    """,
    # 2. Set existing rules to run_id = 1
    """
    UPDATE safety_rules SET run_id = 1 WHERE run_id IS NULL;
    """,
    # 3. Create index on run_id
    """
    CREATE INDEX IF NOT EXISTS idx_rules_run_id ON safety_rules (run_id);
    """,
    # 4. Add evaluation_results JSONB column to extraction_runs
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'extraction_runs' AND column_name = 'evaluation_results'
        ) THEN
            ALTER TABLE extraction_runs ADD COLUMN evaluation_results JSONB;
        END IF;
    END $$;
    """,
    # 5. Add file_url column to extraction_runs
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'extraction_runs' AND column_name = 'file_url'
        ) THEN
            ALTER TABLE extraction_runs ADD COLUMN file_url TEXT;
        END IF;
    END $$;
    """,
    # 6. Add model_reports JSONB column to completed_scans (multi-model support)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'completed_scans' AND column_name = 'model_reports'
        ) THEN
            ALTER TABLE completed_scans ADD COLUMN model_reports JSONB;
        END IF;
    END $$;
    """,
    # 7. Add comparison_data JSONB column to completed_scans
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'completed_scans' AND column_name = 'comparison_data'
        ) THEN
            ALTER TABLE completed_scans ADD COLUMN comparison_data JSONB;
        END IF;
    END $$;
    """,
]
