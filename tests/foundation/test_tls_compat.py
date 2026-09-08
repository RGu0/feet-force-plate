"""The retry fix requires 0.2: verify both existing consumers retain secure CA trust."""
from datetime import UTC, datetime, timedelta
import ssl
from unittest.mock import patch
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
import httpx
import pytest
from techflex_cloud_foundation import InsecureTransportRejected

from client.cloud.access_client import CloudAccessClient
from client.sync.persistent_upload import HttpIngestionClient


@pytest.fixture(params=[CloudAccessClient, HttpIngestionClient])
def make_client(request):
    def create(base_url="https://cloud.test", **kwargs):
        if request.param is HttpIngestionClient:
            kwargs["terminal_id"] = uuid4()
        return request.param(base_url, **kwargs)
    return create


def test_default_trust_requires_certificate_and_hostname_validation(make_client):
    with patch("httpx.Client", wraps=httpx.Client) as constructor:
        client = make_client()
        try:
            context = constructor.call_args.kwargs["verify"]
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname
            assert constructor.call_args.kwargs["trust_env"] is False
        finally:
            client.close()


def test_private_ca_path_loads_the_exact_certificate_into_foundation(make_client, tmp_path):
    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RAY-428 test CA")])
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, algorithm=None)
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    with patch("httpx.Client", wraps=httpx.Client) as constructor:
        client = make_client(verify=str(ca_path))
        try:
            context = constructor.call_args.kwargs["verify"]
            assert context.get_ca_certs(binary_form=True) == [certificate.public_bytes(serialization.Encoding.DER)]
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname
        finally:
            client.close()


def test_insecure_configuration_is_rejected_before_http_client_creation(make_client):
    with patch("httpx.Client") as constructor:
        with pytest.raises(InsecureTransportRejected):
            make_client(verify=False)
        with pytest.raises(InsecureTransportRejected):
            make_client(base_url="http://cloud.test")
        constructor.assert_not_called()


def test_missing_private_ca_does_not_fall_back_to_system_trust(make_client, tmp_path):
    with patch("httpx.Client") as constructor:
        with pytest.raises(FileNotFoundError):
            make_client(verify=str(tmp_path / "missing.pem"))
        constructor.assert_not_called()
