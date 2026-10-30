"""Offline mobile contract export from implemented routes and versioned DTOs.

Service placeholders select the schema surface only; no service is called and
no credentials, endpoint or deployment configuration are loaded.
"""
from __future__ import annotations

import base64
from dataclasses import fields
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, create_model

from cloud.api.app import ServiceContainer, create_app
from cloud.api.access_auth import LicenseDocumentSigner
from cloud.api import errors
from shared.contracts import access_control as access
from shared.contracts import cloud
from shared.contracts.client_sync import (
    canonical_json_bytes, canonical_sha256, encode_segment_metadata)
from shared.contracts import insole_inventory as insole
from shared.contracts import terminal_access as terminal
from shared.contracts import terminal_diagnostics as diagnostics


class ResponseMeta(BaseModel):
    request_id: UUID
    correlation_id: UUID
    server_time: datetime


class BusinessErrorEnvelope(BaseModel):
    error: cloud.ErrorDetail
    meta: ResponseMeta


class LogoutData(BaseModel):
    logged_out: bool


# These return DTOs and statuses mirror app.py's explicit _data_response calls.
_RESPONSE_TYPES = {
    ('/v1/access/activate', 'post'): (access.ActivateAccountResponse, (201,)),
    ('/v1/access/inventory-activate', 'post'): (access.ActivateAccountResponse, (201,)),
    ('/v1/access/login', 'post'): (access.LoginResponse, (200,)),
    ('/v1/access/refresh', 'post'): (access.RefreshResponse, (200,)),
    ('/v1/access/logout', 'post'): (LogoutData, (200,)),
    ('/v1/access/license', 'get'): (access.SignedLicenseV2, (200,)),
    ('/v1/access/terminal-activate', 'post'): (terminal.TerminalCredentialResponse, (201,)),
    ('/v1/access/terminal-refresh', 'post'): (terminal.TerminalCredentialResponse, (200,)),
    ('/v1/access/terminals', 'get'): (terminal.TerminalListResponse, (200,)),
    ('/v1/access/terminals/{client_installation_id}', 'patch'): (terminal.TerminalSummary, (200,)),
    ('/v1/access/terminals/{client_installation_id}/revoke', 'post'): (terminal.TerminalSummary, (200,)),
    ('/v1/inventory/insoles', 'post'): (insole.InsoleRegistrationResponse, (200, 201)),
    ('/v1/inventory/insoles', 'get'): (insole.InsoleChangesResponse, (200,)),
    ('/v1/inventory/insoles/{insole_id}/reports', 'post'): (insole.InsoleReportResponse, (200,)),
    ('/v1/inventory/insoles/{insole_id}/retire', 'post'): (insole.InsoleRetireResponse, (200,)),
    ('/v1/diagnostics', 'post'): (diagnostics.DiagnosticUploadResponse, (200, 201)),
    ('/v1/subjects/resolve', 'post'): (cloud.SubjectSummary, (200,)),
    ('/v1/subjects', 'post'): (cloud.SubjectSummary, (200, 201)),
    ('/v1/consents', 'post'): (cloud.ConsentResponse, (201,)),
    ('/v1/consents/{consent_record_id}/revoke', 'post'): (cloud.ConsentResponse, (200,)),
    ('/v1/sessions', 'post'): (cloud.SessionCreateResponse, (200, 201)),
    ('/v1/sessions/{session_id}/segments/{segment_index}', 'put'): (cloud.SegmentAcknowledgement, (200, 201)),
    ('/v1/sessions/{session_id}/segments', 'get'): (cloud.SegmentListResponse, (200,)),
    ('/v1/sessions/{session_id}/complete', 'post'): (cloud.ManifestCompletionResponse, (200,)),
    ('/v1/sessions/{session_id}/status', 'get'): (cloud.SessionStatusResponse, (200,)),
}


# RAY-656: business error codes each terminal operation can return. Clients
# branch on code; a transport failure has no envelope at all.
_TERMINAL_ERRORS = (
    ('credentials_rejected', errors.TerminalCredentialsRejected),
    ('license_inactive', errors.TerminalLicenseInactive),
    ('seat_limit', errors.TerminalSeatLimitReached),
    ('installation_conflict', errors.TerminalInstallationConflict),
    ('terminal_revoked', errors.TerminalRevoked),
    ('refresh_replayed', errors.TerminalRefreshReplayed),
    ('refresh_expired', errors.TerminalRefreshExpired),
    ('refresh_invalid', errors.TerminalRefreshInvalid),
)
_TERMINAL_OPERATION_ERRORS = {
    ('/v1/access/terminal-activate', 'post'): (
        errors.TerminalCredentialsRejected, errors.TerminalLicenseInactive,
        errors.TerminalSeatLimitReached, errors.TerminalInstallationConflict),
    ('/v1/access/terminal-refresh', 'post'): (
        errors.TerminalRevoked, errors.TerminalRefreshReplayed,
        errors.TerminalRefreshExpired, errors.TerminalRefreshInvalid),
    ('/v1/access/terminals', 'get'): (errors.AuthenticationError, errors.TerminalRevoked),
    ('/v1/access/terminals/{client_installation_id}', 'patch'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.ResourceNotFound),
    ('/v1/access/terminals/{client_installation_id}/revoke', 'post'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.ResourceNotFound),
}

# RAY-778: insole inventory operations. Every one authenticates with a
# terminal bearer token, so a revoked terminal gets E-TRM-401-REVOKED.
_INSOLE_ERRORS = (
    ('identity_registered', errors.InsoleIdentityRegistered),
    ('number_taken', errors.InsoleNumberTaken),
    ('retired', errors.InsoleRetired),
    ('reading_in_future', errors.InsoleReadingInFuture),
    ('cursor_invalid', errors.InsoleCursorInvalid),
)
_TERMINAL_OPERATION_ERRORS.update({
    ('/v1/inventory/insoles', 'post'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.InsoleIdentityRegistered,
        errors.InsoleNumberTaken, errors.IdempotencyConflict),
    ('/v1/inventory/insoles', 'get'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.InsoleCursorInvalid),
    ('/v1/inventory/insoles/{insole_id}/reports', 'post'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.ResourceNotFound,
        errors.InsoleRetired, errors.InsoleReadingInFuture),
    ('/v1/inventory/insoles/{insole_id}/retire', 'post'): (
        errors.AuthenticationError, errors.TerminalRevoked, errors.ResourceNotFound),
})

# RAY-802: terminal diagnostic package upload. The platform support routes
# are not part of the mobile contract (cloud/api/README.md).
_DIAGNOSTICS_ERRORS = (
    ('too_large', errors.DiagnosticTooLarge),
    ('digest_mismatch', errors.DiagnosticDigestMismatch),
    ('content_rejected', errors.DiagnosticContentRejected),
    ('idempotency_conflict', errors.IdempotencyConflict),
    ('terminal_revoked', errors.TerminalRevoked),
)
_TERMINAL_OPERATION_ERRORS[('/v1/diagnostics', 'post')] = (
    errors.AuthenticationError, errors.TerminalRevoked, errors.RequestContractError,
    errors.DiagnosticTooLarge, errors.DiagnosticDigestMismatch,
    errors.DiagnosticContentRejected, errors.IdempotencyConflict)

# RAY-728 R1: subject, consent and session routes also accept the terminal
# access token. The codes below are the terminal-specific outcomes (D1-D6).
_TERMINAL_DATA_ROUTES = (
    ('/v1/subjects/resolve', 'post'),
    ('/v1/subjects', 'post'),
    ('/v1/consents', 'post'),
    ('/v1/consents/{consent_record_id}/revoke', 'post'),
    ('/v1/sessions', 'post'),
    ('/v1/sessions/{session_id}/segments/{segment_index}', 'put'),
    ('/v1/sessions/{session_id}/segments', 'get'),
    ('/v1/sessions/{session_id}/complete', 'post'),
    ('/v1/sessions/{session_id}/status', 'get'),
)
_TERMINAL_OPERATION_ERRORS.update({
    route: (errors.AuthenticationError, errors.TerminalRevoked, errors.TenantAccessDenied)
    for route in _TERMINAL_DATA_ROUTES
})

def _install_schema(model, schemas):
    schema = model.model_json_schema(ref_template='#/components/schemas/{model}')
    schemas.update(schema.pop('$defs', {}))
    schemas[model.__name__] = schema
    return {'$ref': f'#/components/schemas/{model.__name__}'}


def build_openapi():
    placeholders = {field.name: object() for field in fields(ServiceContainer)}
    document = create_app(ServiceContainer(**placeholders)).openapi()
    document['paths'] = {path: document['paths'][path] for path, _ in _RESPONSE_TYPES}
    schemas = document['components']['schemas']
    error_ref = _install_schema(BusinessErrorEnvelope, schemas)
    for (path, method), (data_type, statuses) in _RESPONSE_TYPES.items():
        operation = document['paths'][path][method]
        envelope = create_model(data_type.__name__ + 'Envelope', data=(data_type, ...), meta=(ResponseMeta, ...))
        ref = _install_schema(envelope, schemas)
        operation['responses'] = {
            str(status): {'description': 'Success (200 may be an idempotent replay)',
                          'content': {'application/json': {'schema': ref}}}
            for status in statuses
        }
        # RAY-834: an unhandled server error is 500 E-CLD-500 with the same envelope.
        error_statuses = [400, 401, 403, 404, 409, 422, 500, 503]
        if errors.DiagnosticTooLarge in _TERMINAL_OPERATION_ERRORS.get((path, method), ()):
            error_statuses.append(errors.DiagnosticTooLarge.http_status)
        for status in sorted(error_statuses):
            operation['responses'][str(status)] = {
                'description': 'Business error; use retryable and action together',
                'content': {'application/json': {'schema': error_ref}},
            }
        if (path, method) in _TERMINAL_OPERATION_ERRORS:
            operation['x-ffp-error-codes'] = [
                {'code': error.code, 'http_status': error.http_status,
                 'retryable': error.retryable, 'action': error.action}
                for error in _TERMINAL_OPERATION_ERRORS[(path, method)]]
        # FastAPI cannot infer the Request.stream() body.
        if method == 'put':
            operation['requestBody'] = {'required': True, 'content': {
                'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
            # RAY-825: the X-Segment-Metadata JSON shape follows the payload schema.
            operation['x-ffp-segment-metadata'] = {
                'header': 'X-Segment-Metadata',
                'encoding': 'unpadded base64url of canonical JSON',
                'by_payload_schema': {
                    'raw-segment/1': _install_schema(cloud.SegmentMetadata, schemas),
                    cloud.INSOLE_ARCHIVE_PAYLOAD_SCHEMA: _install_schema(
                        cloud.ArchiveSegmentMetadata, schemas)}}
    document['info']['description'] += (
        ' Offline contract of existing FeetForcePlate routes; not proof of deployed '
        'gait-insole support. Endpoints and TLS profiles are injected by consumers.')
    # Drop unrelated DTOs from conditionally registered operations.
    pending = [document['paths']]
    required = set()
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            reference = value.get('$ref', '')
            prefix = '#/components/schemas/'
            if reference.startswith(prefix) and reference[len(prefix):] not in required:
                name = reference[len(prefix):]
                required.add(name)
                pending.append(schemas[name])
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    document['components']['schemas'] = {name: schemas[name] for name in sorted(required)}
    return document


def build_vectors():
    payload = b'mobile-contract-segment\x00\xff'
    digest = hashlib.sha256(payload).hexdigest()
    metadata = cloud.SegmentMetadata(
        segment_index=0, start_frame_index=0, frame_count=1,
        start_monotonic_ns=100, end_monotonic_ns=200, compression='none',
        cipher='aes-256-gcm', size_bytes=len(payload), sha256=digest,
        payload_schema_version='raw-segment/1')
    meta = {'request_id': str(UUID(int=1)), 'correlation_id': str(UUID(int=2)),
            'server_time': '2026-10-07T00:00:00Z'}
    error_vectors = {}
    for name, error_type in (('digest_mismatch', errors.DigestMismatch),
                             ('schema_unsupported', errors.SchemaUnsupported),
                             ('idempotency_conflict', errors.IdempotencyConflict),
                             ('unavailable', errors.RepositoryUnavailable),
                             ('internal', errors.PlatformError)):
        error_vectors[name] = {'error': {'code': error_type.code,
            'message': 'Synthetic contract fixture', 'retryable': error_type.retryable,
            'action': error_type.action, 'details': {}}, 'meta': meta}
    # Deterministic, synthetic fixture key. Never used as an application key.
    fixture_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b'RAY-641 public test fixture').digest())
    public = fixture_key.public_key().public_bytes_raw()
    document = access.LicenseDocumentV2(
        tenant_id=UUID(int=10), account_id=UUID(int=11), license_id=UUID(int=12),
        hardware_id='FFP-DP4864-000000', status=access.LicenseState.ACTIVE,
        issued_at=datetime(2026, 10, 7, tzinfo=UTC),
        valid_from=datetime(2026, 10, 7, tzinfo=UTC),
        valid_until=datetime(2026, 11, 7, tzinfo=UTC), version=1,
        enabled_features=('fixture.feature',))
    signed = LicenseDocumentSigner(key_id='fixture-license/2',
        public_keys={'fixture-license/2': public}, private_key=fixture_key).sign(document)
    canonical = canonical_json_bytes(document)
    terminal_document = terminal.TerminalLicenseDocument(
        tenant_id=UUID(int=10), account_id=UUID(int=11), license_id=UUID(int=12),
        status=access.LicenseState.ACTIVE, issued_at=datetime(2026, 10, 7, tzinfo=UTC),
        valid_from=datetime(2026, 10, 7, tzinfo=UTC),
        valid_until=datetime(2026, 11, 7, tzinfo=UTC), version=1,
        enabled_features=('fixture.feature',), seats=2)
    terminal_signed = LicenseDocumentSigner(key_id='fixture-license/2',
        public_keys={'fixture-license/2': public}, private_key=fixture_key).sign_terminal(terminal_document)
    terminal_vectors = _terminal_vectors(meta)
    terminal_vectors['license'] = {
        'signed_license': terminal_signed.model_dump(mode='json'),
        'public_key_base64': base64.b64encode(public).decode('ascii'),
        'canonical_hex': canonical_json_bytes(terminal_document).hex(),
        'signature_base64': terminal_signed.signature}
    return {'schema_version': 'mobile-contract-vectors/1',
        'product': 'feet-force-plate', 'errors': error_vectors,
        'success': {'data': {'session_id': str(UUID(int=20)), 'ingest_status': 'RECEIVING',
                            'idempotent_replay': False}, 'meta': meta},
        'session_replay': {'initial_status': 201, 'replay_status': 200,
            'request_headers': {'Idempotency-Key': 'fixture:create:20'},
            'initial_idempotent_replay': False, 'replay_idempotent_replay': True,
            'same_key_different_request_error': 'E-API-409'},
        'segment': {'payload_base64': base64.b64encode(payload).decode('ascii'),
            'sha256': digest, 'metadata': metadata.model_dump(mode='json'),
            'metadata_header': encode_segment_metadata(metadata),
            'canonical_hex': canonical_json_bytes(metadata).hex()},
        'license': {'signed_license': signed.model_dump(mode='json'),
            'public_key_base64': base64.b64encode(public).decode('ascii'),
            'canonical_hex': canonical.hex(), 'signature_base64': signed.signature,
            'negative_cases': ['modified_document', 'modified_signature', 'unknown_key_id']},
        'terminal': terminal_vectors,
        'terminal_data_plane': _terminal_data_plane_vectors(),
        'insole_inventory': _insole_vectors(meta),
        'insole_session_archive': _insole_archive_vectors(),
        'terminal_diagnostics': _diagnostics_vectors(meta)}


def _terminal_vectors(meta):
    """Declarative RAY-656 vectors; cloud tests replay every scenario."""
    envelopes = {
        name: {'http_status': error_type.http_status, 'body': {'error': {
            'code': error_type.code, 'message': 'Synthetic contract fixture',
            'retryable': error_type.retryable, 'action': error_type.action,
            'details': {}}, 'meta': meta}}
        for name, error_type in _TERMINAL_ERRORS}
    installation = str(UUID(int=30))
    return {
        'errors': envelopes,
        'activation_request': {
            'account_name': 'fixture-clinic', 'password': 'fixture-password-0000',
            'terminal_name': 'Front desk', 'client_installation_id': installation,
            'platform': 'ios'},
        'refresh_request': {'refresh_token': 'fixture-refresh-token-not-a-secret-000000',
                            'client_installation_id': installation},
        'refresh_rotation': {
            'replay_grace_seconds': terminal.TERMINAL_REFRESH_REPLAY_GRACE_SECONDS,
            'grace_boundary': 'inclusive',
            'in_grace_replay_returns': 'identical_refresh_token_new_access_token',
            'after_grace_replay_revokes': 'whole_refresh_family',
            # Steps: activate -> rotate once -> act. elapsed is seconds after rotation.
            'scenarios': [
                {'name': 'replay_within_grace', 'elapsed_seconds': 30,
                 'successor_used': False, 'replay': 'original',
                 'expect': {'http_status': 200, 'refresh_token': 'same_as_successor'}},
                {'name': 'replay_after_grace', 'elapsed_seconds': 31,
                 'successor_used': False, 'replay': 'original',
                 'expect': {'http_status': 401, 'code': errors.TerminalRefreshReplayed.code,
                            'successor_code': errors.TerminalRefreshReplayed.code}},
                {'name': 'replay_after_successor_used', 'elapsed_seconds': 0,
                 'successor_used': True, 'replay': 'original',
                 'expect': {'http_status': 401, 'code': errors.TerminalRefreshReplayed.code}},
                {'name': 'refresh_after_revocation', 'elapsed_seconds': 0,
                 'successor_used': False, 'replay': 'successor', 'revoke_first': True,
                 'expect': {'http_status': 401, 'code': errors.TerminalRevoked.code}},
                {'name': 'refresh_after_idle_expiry', 'elapsed_seconds': 31 * 24 * 3600,
                 'successor_used': False, 'replay': 'successor',
                 'expect': {'http_status': 401, 'code': errors.TerminalRefreshExpired.code}},
                {'name': 'unknown_refresh_token', 'elapsed_seconds': 0,
                 'successor_used': False, 'replay': 'unknown',
                 'expect': {'http_status': 401, 'code': errors.TerminalRefreshInvalid.code}},
            ]},
        'seats': {
            'source': 'signed_license.document.seats',
            'counts': 'ACTIVE terminals of the License',
            'scenarios': [
                {'name': 'new_installation_over_limit', 'seats': 2, 'active': 2,
                 'expect': {'http_status': 409, 'code': errors.TerminalSeatLimitReached.code}},
                {'name': 'reactivate_active_installation', 'seats': 2, 'active': 2,
                 'same_installation': True, 'expect': {'http_status': 201}},
                {'name': 'after_revocation', 'seats': 2, 'active': 2, 'revoke_first': True,
                 'expect': {'http_status': 201}},
            ]},
    }



def _terminal_data_plane_vectors():
    """Declarative RAY-728 R1 vectors; cloud tests replay every scenario."""
    denied = {'http_status': errors.TenantAccessDenied.http_status,
              'code': errors.TenantAccessDenied.code}
    revoked = {'http_status': errors.TerminalRevoked.http_status,
               'code': errors.TerminalRevoked.code}
    return {
        'credential': 'terminal access token (POST /v1/access/terminal-activate or '
                      '/v1/access/terminal-refresh); hardware tenant tokens keep working',
        'routes': [f'{method.upper()} {path}' for path, method in _TERMINAL_DATA_ROUTES],
        'x_terminal_id': 'optional; when sent it must equal client_installation_id',
        'terminal_status': 'checked on every request; a revoked terminal gets '
                           f'{errors.TerminalRevoked.code} even with an unexpired token',
        'session_binding': {
            'terminal_id': 'client_installation_id of the caller',
            'client_installation_id': 'client_installation_id of the caller',
            'site_id': None,
            'device_id': 'insole_id of a non-retired pair in the institution inventory; '
                         'any terminal of the institution may use it',
            'existing_session': 'segments, complete and status only for sessions the '
                                'calling terminal created'},
        'license': {
            'new_session': 'current License ACTIVE, within validity and enabling '
                           'screening.start; read on every request, not from the token',
            'upload': 'segments, complete, subject and consent writes need only an '
                      'ACTIVE terminal'},
        'capture_authorization': 'not supported for terminals: X-Capture-Authorization '
                                 'or X-Expected-Manifest-SHA256 is rejected',
        'scenarios': [
            {'name': 'full_upload', 'expect': {'http_status': 201}},
            {'name': 'x_terminal_id_mismatch', 'expect': denied},
            {'name': 'session_names_other_terminal', 'expect': denied},
            {'name': 'site_id_present', 'expect': denied},
            {'name': 'unknown_insole', 'expect': denied},
            {'name': 'retired_insole', 'expect': denied},
            {'name': 'license_without_new_test', 'expect': denied,
             'existing_session_upload': {'http_status': 201}},
            {'name': 'capture_authorization_header', 'expect': denied},
            {'name': 'session_of_other_terminal', 'expect': denied},
            {'name': 'revoked_terminal', 'expect': revoked},
        ],
        'self_revoke': {
            'route': 'POST /v1/access/terminals/{client_installation_id}/revoke',
            'target': 'the calling terminal itself is supported',
            'effects': ['seat released immediately', 'every refresh session of the '
                        'terminal invalidated', f'access token gets {errors.TerminalRevoked.code} '
                        'on /v1/access/* and the data routes until it expires'],
            'repeat': 'returns the revoked terminal unchanged; safe to retry',
            'logout': 'POST /v1/access/logout is for hardware login only and does not '
                      'accept a terminal refresh token'},
        'reactivation': {
            'same_account_same_installation': 'keeps client_installation_id; new refresh '
                                              'family; previous refresh sessions SUPERSEDED',
            'seat': f'consumes a seat again; {errors.TerminalSeatLimitReached.code} when full',
            'other_account': errors.TerminalInstallationConflict.code,
            'sessions_created_before_revoke': 'segments and complete continue after '
                                              're-activation'},
    }


def _insole_vectors(meta):
    """Declarative RAY-778 vectors; cloud tests replay every scenario."""
    left_mac, right_mac = 'C0:FF:EE:00:00:01', 'C0:FF:EE:00:00:02'

    def node(value, *, kind='mac', firmware='1.4.2'):
        return {'identity': {'kind': kind, 'value': value, 'provenance': 'ble_advertisement'},
                'firmware_version': firmware}

    registration = {'institution_number': 'A-001', 'size': 38,
                    'left': node(left_mac), 'right': node(right_mac)}
    at = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    record = insole.InsoleRecord(
        insole_id=UUID(int=50), institution_number='A-001', size=38,
        left=insole.InsoleNode(**node(left_mac), battery=insole.StoredBatteryReading(
            millivolts=3987, percent=82, read_at=at,
            reported_by_client_installation_id=UUID(int=40))),
        right=insole.InsoleNode(**node(right_mac), battery=insole.StoredBatteryReading(
            millivolts=3712, percent=55, read_at=at,
            reported_by_client_installation_id=UUID(int=40))),
        state=insole.InsoleState.IN_USE, state_observed_at=at,
        holder=insole.InsoleHolder(client_installation_id=UUID(int=40),
                                   terminal_name='Front desk'),
        registered_at=at, registered_by_client_installation_id=UUID(int=40),
        revision=3, updated_at=at).model_dump(mode='json')
    envelopes = {}
    for name, error_type in _INSOLE_ERRORS:
        details = ({'existing': record} if error_type in (
            errors.InsoleIdentityRegistered, errors.InsoleNumberTaken) else {})
        envelopes[name] = {'http_status': error_type.http_status, 'body': {'error': {
            'code': error_type.code, 'message': 'Synthetic contract fixture',
            'retryable': error_type.retryable, 'action': error_type.action,
            'details': details}, 'meta': meta}}

    def merge(name, stored, incoming, applied):
        return {'name': name, 'stored_offset_seconds': stored,
                'incoming_offset_seconds': incoming, 'expect_applied': applied}

    return {
        'errors': envelopes,
        'authentication': {
            'credential': 'terminal access token (POST /v1/access/terminal-activate)',
            'scope': 'tenant of the terminal; any ACTIVE terminal of the tenant may '
                     'register, report and retire',
            'other_tenant_insole': {'http_status': 404, 'code': errors.ResourceNotFound.code},
            'revoked_terminal': {'http_status': 401, 'code': errors.TerminalRevoked.code}},
        'registration_request': registration,
        'record': record,
        'registration': {
            'request_headers': {'Idempotency-Key': 'fixture:insole:A-001'},
            'idempotency_key_scope': 'registering client_installation_id',
            'initial_status': 201, 'replay_status': 200,
            'initial_idempotent_replay': False, 'replay_idempotent_replay': True,
            'replay_returns': 'same insole_id at its current revision',
            'same_key_different_request_error': errors.IdempotencyConflict.code,
            'identity_compare': 'kind + value, exact; provenance is not compared',
            'mac_pattern': insole.INSOLE_MAC_PATTERN,
            'non_canonical_mac_examples': ['c0:ff:ee:00:00:01', 'C0-FF-EE-00-00-01',
                                           'C0FFEE000001'],
            'non_canonical_mac_status': 422,
            # Steps: register registration_request, then register `attempt` with a new key.
            'scenarios': [
                {'name': 'same_pair_other_terminal', 'attempt': registration,
                 'expect': {'http_status': 200, 'idempotent_replay': True,
                            'same_insole_id': True}},
                {'name': 'same_mac_other_number',
                 'attempt': {**registration, 'institution_number': 'A-002'},
                 'expect': {'http_status': 409,
                            'code': errors.InsoleIdentityRegistered.code,
                            'existing_institution_number': 'A-001'}},
                {'name': 'same_right_mac_on_left_other_number',
                 'attempt': {**registration, 'institution_number': 'A-003',
                             'left': node(right_mac), 'right': node('C0:FF:EE:00:00:09')},
                 'expect': {'http_status': 409,
                            'code': errors.InsoleIdentityRegistered.code,
                            'existing_institution_number': 'A-001'}},
                {'name': 'same_number_other_mac',
                 'attempt': {**registration, 'left': node('C0:FF:EE:00:00:03'),
                             'right': node('C0:FF:EE:00:00:04')},
                 'expect': {'http_status': 409, 'code': errors.InsoleNumberTaken.code,
                            'existing_institution_number': 'A-001'}},
                {'name': 'same_number_one_side_changed',
                 'attempt': {**registration, 'right': node('C0:FF:EE:00:00:05')},
                 'expect': {'http_status': 409, 'code': errors.InsoleNumberTaken.code,
                            'existing_institution_number': 'A-001'}},
                {'name': 'serial_identity_new_pair',
                 'attempt': {'institution_number': 'A-004', 'size': 40,
                             'left': node('SN-0001', kind='serial', firmware=None),
                             'right': node('SN-0002', kind='serial', firmware=None)},
                 'expect': {'http_status': 201, 'idempotent_replay': False}},
            ],
            'precedence': ['identity owned by another number (left, then right)',
                           'number owned by other identities']},
        'report_request': {
            'state': {'state': 'in_use', 'observed_at': '2026-10-20T08:00:00Z'},
            'left': {'millivolts': 3987, 'percent': 82, 'read_at': '2026-10-20T08:00:00Z'},
            'right': {'millivolts': 3712, 'percent': 55, 'read_at': '2026-10-20T08:00:00Z'}},
        'merge': {
            'rule': 'newer device-side time wins',
            'granularity': ['state', 'left', 'right'],
            'equal_time': 'not applied; the stored reading stands',
            'device_time_fields': {'state': 'observed_at', 'left': 'read_at',
                                   'right': 'read_at'},
            'max_future_skew_seconds': insole.INSOLE_READING_MAX_FUTURE_SKEW_SECONDS,
            'holder': 'reporting terminal while state is in_use, otherwise null',
            'reportable_states': [state.value for state in insole.ReportedInsoleState],
            'retired_reports_error': errors.InsoleRetired.code,
            # Offsets are seconds relative to a common base time.
            'scenarios': [
                merge('newer_reading_applies', 0, 60, True),
                merge('late_stale_reading_ignored', 60, 0, False),
                merge('equal_time_not_applied', 60, 60, False),
                merge('first_reading_applies', None, 0, True),
            ]},
        'download': {
            'route': 'GET /v1/inventory/insoles?cursor=&limit=',
            'cursor': 'opaque; omit or empty for a full download from the beginning',
            'order': 'revision ascending; each pair appears once, at its latest revision',
            'clock_source': 'server-assigned per-tenant revision sequence, never wall clock',
            'deletion': 'none; retired pairs are delivered with state retired',
            'next_cursor': 'always returned; unchanged when the page is empty',
            'default_limit': insole.INSOLE_PAGE_DEFAULT_LIMIT,
            'max_limit': insole.INSOLE_PAGE_MAX_LIMIT,
            'invalid_cursor_error': errors.InsoleCursorInvalid.code,
            'invalid_cursor_example': 'bm90LWEtY3Vyc29y',
            'out_of_range_cursor_example': base64.urlsafe_b64encode(
                b'insole-cursor/1:99999999999999999999').rstrip(b'=').decode('ascii')},
    }

def _insole_archive_vectors():
    """Declarative RAY-825 R1 vectors; cloud tests replay the full upload."""
    parts = (b'insole-archive-part-0\x00\xff', b'insole-archive-part-1')
    segments = []
    for index, payload in enumerate(parts):
        metadata = cloud.ArchiveSegmentMetadata(
            segment_index=index, size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            payload_schema_version=cloud.INSOLE_ARCHIVE_PAYLOAD_SCHEMA)
        header = encode_segment_metadata(metadata)
        segments.append({
            'payload_base64': base64.b64encode(payload).decode('ascii'),
            'metadata': metadata.model_dump(mode='json'),
            'canonical_hex': canonical_json_bytes(metadata).hex(),
            'request_headers': {
                'X-Content-SHA256': metadata.sha256,
                'X-Schema-Version': cloud.INSOLE_ARCHIVE_PAYLOAD_SCHEMA,
                'X-Segment-Metadata': header,
                'Content-Type': 'application/octet-stream'}})
    manifest = cloud.InsoleSessionManifest(
        schema_version=cloud.INSOLE_MANIFEST_SCHEMA, segment_count=len(parts),
        total_bytes=sum(len(payload) for payload in parts),
        segments=tuple(cloud.ArchiveManifestSegment(
            index=item['metadata']['segment_index'], sha256=item['metadata']['sha256'],
            size_bytes=item['metadata']['size_bytes']) for item in segments),
        ended_at=datetime(2026, 10, 25, 12, 58, 0, 250000, tzinfo=UTC),
        local_quality_outcome=cloud.ValidityStatus.VALID)
    return {
        'payload_schema': cloud.INSOLE_ARCHIVE_PAYLOAD_SCHEMA,
        'manifest_schema': cloud.INSOLE_MANIFEST_SCHEMA,
        'pairing': dict(cloud.MANIFEST_SCHEMA_FOR_PAYLOAD),
        'session_versions': {'app': 'gait-insole/1.0.0', 'protocol_profile': 'insole-walk/1',
                             'payload_schema': cloud.INSOLE_ARCHIVE_PAYLOAD_SCHEMA,
                             'calibration': 'insole-uncalibrated/1'},
        'segment_metadata_fields': sorted(cloud.ArchiveSegmentMetadata.model_fields),
        'segment_metadata_extra_fields': 'rejected (E-API-400)',
        'metadata_header': 'unpadded base64url of canonical JSON: sorted keys, no '
                           'whitespace, UTF-8',
        'segments': segments,
        'manifest': {
            'body': manifest.model_dump(mode='json'),
            'canonical_hex': canonical_json_bytes(manifest).hex(),
            'sha256': canonical_sha256(manifest),
            'request_headers': {
                'X-Content-SHA256': canonical_sha256(manifest),
                'X-Schema-Version': cloud.INSOLE_MANIFEST_SCHEMA},
            'idempotency_key': 'also send Idempotency-Key: chosen by the client, unique '
                               'per session and stable across retries of its completion',
            'digest': 'sha256 of the canonical JSON the server re-serializes from the '
                      'parsed body: sorted keys, no whitespace. Send ended_at in UTC as '
                      'YYYY-MM-DDTHH:MM:SS[.ffffff]Z (microseconds only when non-zero); '
                      'the server digests its own re-serialization, so any other form '
                      'gets a digest mismatch unless it re-serializes identically'},
        'rules': {
            'local_quality_outcome': 'required; only VALID completes to INGESTED, other '
                                     f'values get {errors.QualityGateRejected.code} '
                                     f'{errors.QualityGateRejected.action}',
            'schema_pairing': 'a manifest whose schema_version is not paired with the '
                              f'session payload_schema gets {errors.SchemaUnsupported.code} '
                              f'{errors.SchemaUnsupported.action}',
            'segment_schema': 'segment payload_schema_version must equal the session '
                              f'payload_schema, else {errors.SchemaUnsupported.code}',
            'segment_set': 'manifest segments must equal the received parts by index, '
                           f'sha256 and size_bytes, else {errors.ManifestIncomplete.code} '
                           f'{errors.ManifestIncomplete.action}'},
        'scenarios': [
            {'name': 'full_upload', 'expect': {'ingest_status': 'INGESTED'}},
            {'name': 'session_manifest_for_archive_session',
             'expect': {'http_status': 422, 'code': errors.SchemaUnsupported.code}},
            {'name': 'quality_not_valid',
             'expect': {'http_status': 422, 'code': errors.QualityGateRejected.code}},
            {'name': 'frame_fields_in_metadata',
             'expect': {'http_status': 400, 'code': errors.RequestContractError.code}},
            {'name': 'manifest_size_differs_from_part',
             'expect': {'http_status': 422, 'code': errors.ManifestIncomplete.code}},
        ],
    }


def _diagnostics_vectors(meta):
    """Declarative RAY-802 vectors; cloud tests replay every scenario.

    Package lines carry ``{tenant_id}`` and ``{terminal_id}``: substitute the
    uploading terminal's tenant and client_installation_id. ``example`` shows
    the result for fixed ids.
    """
    envelopes = {}
    for name, error_type in _DIAGNOSTICS_ERRORS:
        details = {}
        if error_type is errors.DiagnosticTooLarge:
            details = {'max_bytes': diagnostics.DIAGNOSTICS_MAX_BYTES}
        elif error_type is errors.DiagnosticContentRejected:
            details = {'line': 3, 'reason': diagnostics.DiagnosticRejectionReason.IDENTITY_DETECTED.value}
        envelopes[name] = {'http_status': error_type.http_status, 'body': {'error': {
            'code': error_type.code, 'message': 'Synthetic contract fixture',
            'retryable': error_type.retryable, 'action': error_type.action,
            'details': details}, 'meta': meta}}

    # ASCII escapes keep vectors.json ASCII-only; the lines stay valid JSON
    # and decode to the same text as the client's raw UTF-8.
    def line(**fields):
        return json.dumps(fields, separators=(',', ':'))

    header_fields = {
        'kind': 'header', 'exported_at': '2026-10-29T06:51:33.000Z', 'app_version': '1.6.0+42',
        'cloud_environment': 'integration', 'platform': 'android', 'os_version': '15',
        'terminal_id': '{terminal_id}', 'tenant_id': '{tenant_id}',
        'format': diagnostics.DIAGNOSTICS_FORMAT, 'dropped_lines': 0}
    header = line(**header_fields)
    log = line(kind='log', t='2026-10-29T06:40:00.000Z', level='info', cat='ble',
               msg='connected', fields={'device_name': 'Insole-L', 'mac_address': 'C0:FF:EE:00:00:01'})
    command = line(kind='command', t='2026-10-29T06:40:01.000Z', command='READ_BATTERY',
                   params='', expected_reply='BAT', actual_reply='BAT 3987', elapsed_ms=42,
                   status='success', ending='replied')
    redacted = line(kind='log', t='2026-10-29T06:41:00.000Z', level='warning', cat='subject',
                    msg='lookup for <redacted> at <redacted:phone>',
                    fields={'subject_uuid': '8d0b9c1e-5f2a-4c4e-9b8a-0d6f3e2a1b7c',
                            'patient_name': '<redacted>', 'contactTel': '<redacted>',
                            '<redacted:phone>': 'seen', 'retries': [1, 2]},
                    error='timeout', stack='#0 main')
    package = [header, log, command, redacted]

    def rejected(name, lines, line_number, reason):
        return {'name': name, 'lines': lines, 'expect': {
            'http_status': errors.DiagnosticContentRejected.http_status,
            'code': errors.DiagnosticContentRejected.code,
            'details': {'line': line_number, 'reason': reason.value}}}

    reason = diagnostics.DiagnosticRejectionReason

    def identity(name, **fields):
        return rejected(f'identity_{name}', [header, log, line(**{
            'kind': 'log', 't': '2026-10-29T06:42:00.000Z', 'level': 'info', 'cat': 'app',
            'msg': 'ok', **fields})], 3, reason.IDENTITY_DETECTED)

    example_ids = {'tenant_id': str(UUID(int=10)), 'terminal_id': str(UUID(int=30))}
    example = ''.join(
        entry.replace('{tenant_id}', example_ids['tenant_id']).replace(
            '{terminal_id}', example_ids['terminal_id']) + '\n'
        for entry in package).encode('utf-8')
    return {
        'errors': envelopes,
        'route': 'POST /v1/diagnostics',
        'credential': 'terminal access token (POST /v1/access/terminal-activate); any '
                      'ACTIVE terminal uploads its own export',
        'constants': {
            'format': diagnostics.DIAGNOSTICS_FORMAT,
            'media_type': diagnostics.DIAGNOSTICS_MEDIA_TYPE,
            'max_bytes': diagnostics.DIAGNOSTICS_MAX_BYTES,
            'max_bytes_applies_to': 'uncompressed body; Content-Encoding is not accepted',
            'retention_days': diagnostics.DIAGNOSTICS_RETENTION_DAYS,
            'sha256_pattern': diagnostics.DIAGNOSTICS_SHA256_PATTERN,
            'redacted_value': diagnostics.DIAGNOSTICS_REDACTED_VALUE},
        'request_headers': {
            'Content-Type': diagnostics.DIAGNOSTICS_MEDIA_TYPE,
            'Idempotency-Key': 'fixture:diagnostics:1',
            'X-Content-SHA256': 'lowercase hex SHA-256 of the exact body bytes'},
        'idempotency_key_scope': 'uploading client_installation_id',
        'response': {
            'fields': sorted(diagnostics.DiagnosticUploadResponse.model_fields),
            'expires_at': f'received_at + {diagnostics.DIAGNOSTICS_RETENTION_DAYS} days',
            'replay': 'same key and same SHA-256 returns 200 with the identical body'},
        'package': {
            'line_separator': '\n; the last line ends with it',
            'first_line': 'header, format ' + diagnostics.DIAGNOSTICS_FORMAT,
            'header_ids': 'tenant_id and terminal_id equal the token tenant and '
                          'client_installation_id',
            'line_fields': {kind: sorted(names)
                            for kind, names in diagnostics.DIAGNOSTICS_LINE_FIELDS.items()},
            'identity_screen': 'every string, key or value, at any depth: no mobile, '
                               'landline, e-mail or resident ID number; a key the client '
                               'Redactor treats as identity holds only redacted_value',
            'rejection': 'whole package; details carry only line (1-based) and reason',
            'rejection_reasons': [item.value for item in reason],
            'placeholders': ['{tenant_id}', '{terminal_id}'],
            'lines': package,
            'example_ids': example_ids,
            'example_sha256': hashlib.sha256(example).hexdigest(),
            'example_size_bytes': len(example)},
        # Steps: each scenario uploads with a new Idempotency-Key unless noted.
        'scenarios': [
            {'name': 'created', 'lines': package, 'expect': {'http_status': 201}},
            {'name': 'replay', 'after': 'created', 'same_key': True, 'lines': package,
             'expect': {'http_status': 200, 'body': 'identical to created'}},
            {'name': 'idempotency_conflict', 'after': 'created', 'same_key': True,
             'lines': package[:3],
             'expect': {'http_status': errors.IdempotencyConflict.http_status,
                        'code': errors.IdempotencyConflict.code}},
            {'name': 'digest_mismatch', 'lines': package, 'declared_sha256': '0' * 64,
             'expect': {'http_status': errors.DiagnosticDigestMismatch.http_status,
                        'code': errors.DiagnosticDigestMismatch.code}},
            {'name': 'over_limit', 'size_bytes': diagnostics.DIAGNOSTICS_MAX_BYTES + 1,
             'expect': {'http_status': errors.DiagnosticTooLarge.http_status,
                        'code': errors.DiagnosticTooLarge.code,
                        'details': {'max_bytes': diagnostics.DIAGNOSTICS_MAX_BYTES}}},
            {'name': 'revoked_terminal', 'lines': package, 'revoke_first': True,
             'expect': {'http_status': errors.TerminalRevoked.http_status,
                        'code': errors.TerminalRevoked.code}},
            rejected('not_json', [header, '{"kind":"log",'], 2, reason.NOT_JSON),
            rejected('header_missing', [log, header], 1, reason.HEADER_MISSING),
            rejected('format_unsupported', [line(**{
                **header_fields, 'format': 'gait-insole-diagnostics/2'})], 1,
                reason.FORMAT_UNSUPPORTED),
            rejected('unknown_kind', [header, line(kind='audit', t='2026-10-29T06:40:00.000Z')],
                     2, reason.UNKNOWN_KIND),
            rejected('second_header', [header, header], 2, reason.UNKNOWN_KIND),
            rejected('unknown_field', [header, command, line(
                kind='log', t='2026-10-29T06:40:00.000Z', level='info', cat='app', msg='ok',
                timeline=[])], 3, reason.UNKNOWN_FIELD),
            rejected('header_mismatch', [line(**{
                **header_fields, 'tenant_id': str(UUID(int=99))})], 1, reason.HEADER_MISMATCH),
            identity('mobile_in_msg', msg='call 138 1234 5678'),
            identity('full_width_mobile', msg='电话１３８１２３４５６７８'),
            identity('landline', error='dial 010-12345678'),
            identity('email', fields={'note': 'from li.wei@example.com'}),
            identity('resident_id', fields={'list': ['11010519491231002X']}),
            identity('name_key', fields={'subjectName': 'Wang Fang'}),
            identity('tel_suffix_key', fields={'nested': {'home_tel': 'x'}}),
            identity('chinese_key', fields={'姓名': '王芳'}),
            identity('phone_as_key', fields={'13812345678': 'seen'}),
            identity('allowed_key_with_sensitive_prefix', fields={'contact_device_name': 'x'}),
        ]}


def main():
    root = Path(__file__).resolve().parents[1] / 'contracts' / 'mobile'
    root.mkdir(parents=True, exist_ok=True)
    for name, document in (('openapi.json', build_openapi()), ('vectors.json', build_vectors())):
        (root / name).write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
