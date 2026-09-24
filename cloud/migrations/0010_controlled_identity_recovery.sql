BEGIN;

-- The case is bound once to the sealed local session and the existing cloud
-- subject. Plaintext name/contact never enter this table or terminal response.
CREATE TABLE ops.identity_recovery_cases (
    case_id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES iam.tenants(tenant_id),
    terminal_id uuid NOT NULL,
    session_id uuid NOT NULL,
    original_subject_uuid uuid NOT NULL,
    cloud_subject_uuid uuid NOT NULL,
    envelope_sha256 text NOT NULL CHECK (envelope_sha256 ~ '^[0-9a-f]{64}$'),
    identifier_issuer text NOT NULL,
    identifier_type text NOT NULL,
    key_sha256 text NOT NULL CHECK (key_sha256 ~ '^[0-9a-f]{64}$'),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    masked_clue text,
    status text NOT NULL CHECK (status IN ('PENDING','MATCHED','DENIED','EXPIRED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, case_id),
    UNIQUE (tenant_id, session_id),
    UNIQUE (tenant_id, key_sha256),
    FOREIGN KEY (tenant_id, cloud_subject_uuid)
        REFERENCES subject.subjects(tenant_id, subject_uuid),
    CHECK (original_subject_uuid <> cloud_subject_uuid)
);

ALTER TABLE ops.identity_recovery_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.identity_recovery_cases FORCE ROW LEVEL SECURITY;
CREATE POLICY identity_recovery_cases_tenant_isolation ON ops.identity_recovery_cases
USING (tenant_id = ops.current_tenant_id())
WITH CHECK (tenant_id = ops.current_tenant_id());

REVOKE ALL ON ops.identity_recovery_cases FROM PUBLIC;
GRANT SELECT, INSERT ON ops.identity_recovery_cases TO ffp_tenant_app;
GRANT SELECT, INSERT, UPDATE ON ops.identity_recovery_cases TO ffp_platform_app;

COMMIT;
