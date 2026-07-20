BEGIN;

CREATE SCHEMA IF NOT EXISTS reporting;

CREATE OR REPLACE FUNCTION reporting.reject_immutable_report_row()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'report versions and artifacts are immutable';
END;
$$;

CREATE TABLE reporting.reports (
    report_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    session_id uuid NOT NULL,
    status text NOT NULL
        CHECK (status IN ('NOT_AVAILABLE', 'BASIC_READY', 'CLOUD_ANALYZING', 'FULL_READY', 'CLOUD_FAILED')),
    latest_version integer CHECK (latest_version IS NULL OR latest_version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, session_id),
    UNIQUE (tenant_id, report_id)
);

CREATE TABLE reporting.report_versions (
    report_version_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    report_id uuid NOT NULL REFERENCES reporting.reports(report_id),
    version_number integer NOT NULL CHECK (version_number > 0),
    kind text NOT NULL CHECK (kind IN ('BASIC', 'CLOUD_COMPLETE')),
    report_schema_version text NOT NULL,
    source_analysis_run_id uuid,
    document_json jsonb NOT NULL,
    document_sha256 text NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
    generated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, report_id, version_number),
    UNIQUE (tenant_id, report_id, source_analysis_run_id)
);

CREATE TABLE reporting.report_artifacts (
    report_artifact_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    report_version_id uuid NOT NULL
        REFERENCES reporting.report_versions(report_version_id),
    object_key text NOT NULL,
    content_type text NOT NULL CHECK (content_type = 'application/pdf'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    renderer_version text NOT NULL,
    template_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, object_key),
    UNIQUE (tenant_id, report_version_id, sha256)
);

CREATE TABLE reporting.report_exports (
    report_export_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    report_version_id uuid NOT NULL
        REFERENCES reporting.report_versions(report_version_id),
    actor_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('PREVIEW', 'EXPORT_PDF', 'PRINT')),
    occurred_at timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER report_versions_immutable
BEFORE UPDATE OR DELETE ON reporting.report_versions
FOR EACH ROW EXECUTE FUNCTION reporting.reject_immutable_report_row();

CREATE TRIGGER report_artifacts_immutable
BEFORE UPDATE OR DELETE ON reporting.report_artifacts
FOR EACH ROW EXECUTE FUNCTION reporting.reject_immutable_report_row();

CREATE TRIGGER report_exports_immutable
BEFORE UPDATE OR DELETE ON reporting.report_exports
FOR EACH ROW EXECUTE FUNCTION reporting.reject_immutable_report_row();

CREATE INDEX reports_session_idx
ON reporting.reports (tenant_id, session_id);

CREATE INDEX report_versions_latest_idx
ON reporting.report_versions (tenant_id, report_id, version_number DESC);

ALTER TABLE reporting.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.report_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.report_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.report_exports ENABLE ROW LEVEL SECURITY;

CREATE POLICY reports_tenant_policy ON reporting.reports
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY report_versions_tenant_policy ON reporting.report_versions
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY report_artifacts_tenant_policy ON reporting.report_artifacts
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY report_exports_tenant_policy ON reporting.report_exports
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

COMMIT;
