BEGIN;

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE OR REPLACE FUNCTION analysis.reject_versioned_definition_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'versioned analysis definitions and results are immutable';
END;
$$;

CREATE OR REPLACE FUNCTION analysis.guard_analysis_run_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.session_id IS DISTINCT FROM NEW.session_id
       OR OLD.pipeline_version IS DISTINCT FROM NEW.pipeline_version
       OR OLD.algorithm_set_version IS DISTINCT FROM NEW.algorithm_set_version
       OR OLD.model_set_version IS DISTINCT FROM NEW.model_set_version
       OR OLD.report_schema_version IS DISTINCT FROM NEW.report_schema_version
       OR OLD.calibration_version IS DISTINCT FROM NEW.calibration_version
       OR OLD.payload_schema_version IS DISTINCT FROM NEW.payload_schema_version
       OR OLD.protocol_profile_version IS DISTINCT FROM NEW.protocol_profile_version
       OR OLD.input_manifest_sha256 IS DISTINCT FROM NEW.input_manifest_sha256
       OR OLD.parameters_sha256 IS DISTINCT FROM NEW.parameters_sha256 THEN
        RAISE EXCEPTION 'analysis run identity is immutable';
    END IF;
    IF OLD.status IN ('SUCCEEDED', 'FAILED', 'UNSUPPORTED', 'CANCELED') THEN
        RAISE EXCEPTION 'terminal analysis runs are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE analysis.algorithm_versions (
    algorithm_id text NOT NULL,
    semantic_version text NOT NULL,
    descriptor jsonb NOT NULL,
    descriptor_sha256 text NOT NULL CHECK (descriptor_sha256 ~ '^[0-9a-f]{64}$'),
    validation_status text NOT NULL
        CHECK (validation_status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (algorithm_id, semantic_version)
);

CREATE TABLE analysis.pipeline_versions (
    pipeline_version text PRIMARY KEY,
    definition jsonb NOT NULL,
    definition_sha256 text NOT NULL CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE analysis.analysis_runs (
    analysis_run_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    session_id uuid NOT NULL,
    pipeline_version text NOT NULL,
    algorithm_set_version text NOT NULL,
    model_set_version text NOT NULL,
    report_schema_version text NOT NULL,
    calibration_version text NOT NULL,
    payload_schema_version text NOT NULL,
    protocol_profile_version text NOT NULL,
    input_manifest_sha256 text NOT NULL
        CHECK (input_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    parameters_sha256 text NOT NULL CHECK (parameters_sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'UNSUPPORTED', 'CANCELED')),
    capability_status text NOT NULL
        CHECK (capability_status IN ('SUPPORTED', 'DEGRADED', 'UNSUPPORTED')),
    source_event_id uuid NOT NULL,
    correlation_id uuid NOT NULL,
    error_code text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, session_id, pipeline_version, algorithm_set_version, model_set_version, report_schema_version, calibration_version, payload_schema_version, protocol_profile_version, input_manifest_sha256, parameters_sha256)
);

CREATE TABLE analysis.feature_sets (
    feature_set_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL REFERENCES analysis.analysis_runs(analysis_run_id),
    pipeline_version text NOT NULL,
    calibration_version text NOT NULL,
    input_manifest_sha256 text NOT NULL,
    parameters_sha256 text NOT NULL,
    cache_key text NOT NULL CHECK (cache_key ~ '^[0-9a-f]{64}$'),
    object_key text NOT NULL,
    object_sha256 text NOT NULL CHECK (object_sha256 ~ '^[0-9a-f]{64}$'),
    safe_summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, cache_key)
);

CREATE TABLE analysis.metric_results (
    metric_result_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL REFERENCES analysis.analysis_runs(analysis_run_id),
    metric_id text NOT NULL,
    metric_definition_version text NOT NULL,
    algorithm_id text NOT NULL,
    algorithm_version text NOT NULL,
    value_numeric double precision,
    value_text text,
    value_json jsonb,
    unit text NOT NULL,
    interpretation_code text,
    validation_status text NOT NULL
        CHECK (validation_status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    evidence_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, analysis_run_id, metric_id, metric_definition_version),
    CHECK (num_nonnulls(value_numeric, value_text, value_json) = 1)
);

CREATE TRIGGER algorithm_versions_immutable
BEFORE UPDATE OR DELETE ON analysis.algorithm_versions
FOR EACH ROW EXECUTE FUNCTION analysis.reject_versioned_definition_mutation();

CREATE TRIGGER pipeline_versions_immutable
BEFORE UPDATE OR DELETE ON analysis.pipeline_versions
FOR EACH ROW EXECUTE FUNCTION analysis.reject_versioned_definition_mutation();

CREATE TRIGGER analysis_run_identity_guard
BEFORE UPDATE ON analysis.analysis_runs
FOR EACH ROW EXECUTE FUNCTION analysis.guard_analysis_run_update();

CREATE TRIGGER feature_sets_immutable
BEFORE UPDATE OR DELETE ON analysis.feature_sets
FOR EACH ROW EXECUTE FUNCTION analysis.reject_versioned_definition_mutation();

CREATE TRIGGER metric_results_immutable
BEFORE UPDATE OR DELETE ON analysis.metric_results
FOR EACH ROW EXECUTE FUNCTION analysis.reject_versioned_definition_mutation();

CREATE INDEX analysis_runs_queue_idx
ON analysis.analysis_runs (status, created_at)
WHERE status IN ('QUEUED', 'RUNNING');

CREATE INDEX analysis_runs_session_idx
ON analysis.analysis_runs (tenant_id, session_id, created_at DESC);

ALTER TABLE analysis.analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.feature_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.metric_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY analysis_runs_tenant_policy ON analysis.analysis_runs
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY feature_sets_tenant_policy ON analysis.feature_sets
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY metric_results_tenant_policy ON analysis.metric_results
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

COMMIT;
