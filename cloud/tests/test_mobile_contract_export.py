from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from cloud.api.contract_export import build_openapi, build_vectors


def test_export_covers_mobile_routes_and_actual_wire_shapes():
    document = build_openapi()
    assert '/v1/access/login' in document['paths']
    assert '/v1/subjects' in document['paths']
    assert '/v1/consents' in document['paths']
    assert '/v1/sessions/{session_id}/status' in document['paths']
    operation = document['paths']['/v1/sessions']['post']
    assert {'200', '201', '422'}.issubset(operation['responses'])
    assert operation['responses']['201']['content']['application/json']['schema']['$ref'].endswith('SessionCreateResponseEnvelope')
    upload = document['paths']['/v1/sessions/{session_id}/segments/{segment_index}']['put']
    assert upload['requestBody']['content']['application/octet-stream']['schema']['format'] == 'binary'
    assert upload['responses']['422']['content']['application/json']['schema']['$ref'].endswith('BusinessErrorEnvelope')
    assert document['components']['schemas']['BusinessErrorEnvelope']['required'] == ['error', 'meta']
    assert 'servers' not in document


def test_vectors_have_verifiable_bytes_and_signature_without_secret_material():
    vectors = build_vectors()
    segment = vectors['segment']
    assert hashlib.sha256(base64.b64decode(segment['payload_base64'])).hexdigest() == segment['sha256']
    assert json.loads(base64.urlsafe_b64decode(segment['metadata_header'] + '===')) == segment['metadata']
    signature = vectors['license']
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(signature['public_key_base64']))
    public.verify(base64.b64decode(signature['signature_base64']), bytes.fromhex(signature['canonical_hex']))
    assert vectors['session_replay']['initial_status'] == 201
    assert vectors['session_replay']['replay_status'] == 200
    assert 'private_key' not in json.dumps(vectors)
    assert vectors['errors']['schema_unsupported']['error']['action'] == 'UPDATE_CLIENT'
    assert vectors['errors']['digest_mismatch']['error']['action'] == 'RESEAL_SEGMENT'


def test_published_artifacts_match_generator():
    root = Path(__file__).resolve().parents[1] / 'contracts' / 'mobile'
    assert json.loads((root / 'openapi.json').read_text()) == build_openapi()
    assert json.loads((root / 'vectors.json').read_text()) == build_vectors()


def test_signature_negative_cases_are_rejected():
    import pytest
    from cryptography.exceptions import InvalidSignature
    fixture = build_vectors()['license']
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(fixture['public_key_base64']))
    signature = base64.b64decode(fixture['signature_base64'])
    with pytest.raises(InvalidSignature):
        public.verify(signature, bytes.fromhex(fixture['canonical_hex']) + b' ')
    with pytest.raises(InvalidSignature):
        public.verify(bytes([signature[0] ^ 1]) + signature[1:], bytes.fromhex(fixture['canonical_hex']))


def test_success_fixture_uses_real_response_dto():
    from shared.contracts.cloud import SessionCreateResponse
    SessionCreateResponse.model_validate(build_vectors()['success']['data'])


def test_terminal_routes_and_distinct_error_codes_are_published():
    document = build_openapi()
    activate = document['paths']['/v1/access/terminal-activate']['post']
    refresh = document['paths']['/v1/access/terminal-refresh']['post']
    assert activate['responses']['201']['content']['application/json']['schema']['$ref'].endswith(
        'TerminalCredentialResponseEnvelope')
    request_schema = document['components']['schemas']['TerminalActivationRequest']
    assert 'activation_code' not in request_schema['properties']
    assert set(request_schema['required']) == {
        'account_name', 'password', 'terminal_name', 'client_installation_id', 'platform'}
    refresh_codes = {entry['code'] for entry in refresh['x-ffp-error-codes']}
    assert refresh_codes == {
        'E-TRM-401-REVOKED', 'E-TRM-401-REFRESH-REPLAYED',
        'E-TRM-401-REFRESH-EXPIRED', 'E-TRM-401-REFRESH-INVALID'}
    assert 'E-TRM-409-SEAT-LIMIT' in {entry['code'] for entry in activate['x-ffp-error-codes']}
    for path in ('/v1/access/terminals', '/v1/access/terminals/{client_installation_id}',
                 '/v1/access/terminals/{client_installation_id}/revoke'):
        assert path in document['paths']
    license_schema = document['components']['schemas']['TerminalLicenseDocument']
    assert 'seats' in license_schema['required']


def test_terminal_vectors_cover_each_error_and_verify_signed_seats():
    vectors = build_vectors()['terminal']
    codes = [entry['body']['error']['code'] for entry in vectors['errors'].values()]
    assert len(codes) == len(set(codes))
    for name in ('terminal_revoked', 'seat_limit', 'refresh_replayed', 'refresh_expired'):
        assert name in vectors['errors']
    assert vectors['refresh_rotation']['replay_grace_seconds'] == 30
    fixture = vectors['license']
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(fixture['public_key_base64']))
    public.verify(base64.b64decode(fixture['signature_base64']), bytes.fromhex(fixture['canonical_hex']))
    assert json.loads(bytes.fromhex(fixture['canonical_hex']))['seats'] == 2
