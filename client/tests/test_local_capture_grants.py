from uuid import uuid4

import pytest

from client.app.institution_store import InstitutionLocalStore
from client.workflow.models import ScreeningParticipantContext
from client.workflow.participant import AnalysisProfile, CreateSubjectRequest
from client.workflow.protocol import default_standard_protocol
from shared.contracts.capture_grants import CaptureGrant


class Key:
    def get_key(self):
        return b"k" * 32


def open_store(path):
    return InstitutionLocalStore.open(path, key_provider=Key(), query_index_key=b"q" * 32)


def participant(store):
    subject = store.create(CreateSubjectRequest(tenant_id="tenant", analysis_profile=AnalysisProfile.unknown()))
    return ScreeningParticipantContext(subject.subject_uuid, "consent")


def grant():
    return CaptureGrant(session_id=uuid4(), token="private-capture-token-" + uuid4().hex)


def test_assignment_encryption_exhaustion_and_reopen(tmp_path):
    from client.app.institution_store import CaptureGrantExhausted

    store = open_store(tmp_path)
    context = participant(store)
    item = grant()
    store.add_capture_grants("tenant", "installation", (item,))
    session_id = store.create_session(context, default_standard_protocol().snapshot(), "tenant", "installation")
    assert session_id == str(item.session_id)
    assert store.capture_credential(session_id).token == item.token
    store.close()
    assert item.token.get_secret_value().encode() not in (tmp_path / "institution.sqlite3").read_bytes()
    store = open_store(tmp_path)
    with pytest.raises(CaptureGrantExhausted):
        store.create_session(context, default_standard_protocol().snapshot(), "tenant", "installation")
    assert store.db.execute("SELECT COUNT(*) FROM institution_sessions").fetchone()[0] == 1
    store.mark_incomplete(session_id)
    assert store.capture_grant_state(session_id) == "BURNED"
    assert store.session_status(session_id) == "INCOMPLETE"


def test_assignment_insert_failure_rolls_back_and_binding_rejected(tmp_path):
    store = open_store(tmp_path)
    context = participant(store)
    item = grant()
    store.add_capture_grants("tenant", "installation", (item,))
    with pytest.raises(ValueError):
        store.create_session(context, default_standard_protocol().snapshot(), "other", "installation")
    store.db.execute("CREATE TRIGGER fail_session BEFORE INSERT ON institution_sessions BEGIN SELECT RAISE(ABORT, 'forced'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.create_session(context, default_standard_protocol().snapshot(), "tenant", "installation")
    assert store.capture_grant_state(str(item.session_id)) == "AVAILABLE"
    assert store.db.execute("SELECT COUNT(*) FROM institution_sessions").fetchone()[0] == 0


def test_pool_capacity_duplicate_and_cross_binding(tmp_path):
    store = open_store(tmp_path)
    items = tuple(grant() for _ in range(50))
    store.add_capture_grants("tenant", "installation", items)
    for tenant, installation, batch in (
        ("tenant", "installation", (items[0],)),
        ("other", "installation", (items[0],)),
        ("tenant", "other", (items[0],)),
        ("tenant", "other", (CaptureGrant(session_id=uuid4(), token=items[0].token),)),
        ("tenant", "installation", (grant(),)),
    ):
        with pytest.raises(ValueError):
            store.add_capture_grants(tenant, installation, batch)
    assert store.db.execute("SELECT COUNT(*) FROM institution_capture_grants").fetchone()[0] == 50


def test_formal_binding_required_and_legacy_uuid_not_replaced(tmp_path):
    store = open_store(tmp_path)
    context = participant(store)
    protocol = default_standard_protocol().snapshot()
    with pytest.raises(TypeError):
        store.create_session(context, protocol)
    legacy = store.create_engineering_session(context, protocol)
    with pytest.raises(KeyError):
        store.capture_credential(legacy)
    assert store.session_status(legacy) == "ACQUIRING"


def test_invalid_retired_and_foreign_installation_never_reassign(tmp_path):
    from client.app.institution_store import CaptureGrantExhausted
    store = open_store(tmp_path)
    context = participant(store)
    protocol = default_standard_protocol().snapshot()
    item = grant()
    store.add_capture_grants("tenant", "installation", (item,))
    with pytest.raises(CaptureGrantExhausted):
        store.create_session(context, protocol, "tenant", "other-installation")
    with pytest.raises(KeyError):
        store.capture_credential(str(item.session_id))
    session_id = store.create_session(context, protocol, "tenant", "installation")
    store._set_session_status(session_id, "INVALID")
    assert store.capture_grant_state(session_id) == "BURNED"
    store.mark_capture_grant_retired(session_id)
    assert store.capture_grant_state(session_id) == "RETIRED"
    with pytest.raises(KeyError):
        store.capture_credential(session_id)
    with pytest.raises(CaptureGrantExhausted):
        store.create_session(context, protocol, "tenant", "installation")
    assert store.session_status(session_id) == "INVALID"


def test_duplicate_in_batch_rolls_back_whole_batch(tmp_path):
    store = open_store(tmp_path)
    item = grant()
    with pytest.raises(ValueError):
        store.add_capture_grants("tenant", "installation", (item, item))
    assert store.available_capture_grants("tenant", "installation") == 0
