#!/usr/bin/env python3
"""Manage the private, loopback-only RAY-513 PostgreSQL test cluster."""

from __future__ import annotations

from datetime import UTC, datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
from urllib.parse import quote, urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(r"C:\FeetForcePlate\local-labs\ray513-postgres-20261010")
DATA_ROOT = RUNTIME_ROOT / "data"
PRIVATE_ROOT = RUNTIME_ROOT / "private"
LOG_ROOT = RUNTIME_ROOT / "logs"
CREDENTIALS_PATH = PRIVATE_ROOT / "credentials.json"
POSTGRES_BIN = Path(r"C:\Program Files\PostgreSQL\16\bin")
ACL_SCRIPT = REPOSITORY_ROOT / "scripts" / "local_postgres_private_acl.ps1"
HOST = "127.0.0.1"
PORT = 55432
DATABASE = "ffp_ray513_test"
ADMIN_ROLE = "ffp_ray513_test_admin"
APPLICATION_ROLES = {
    "tenant": ("ffp_ray513_test_tenant", "ffp_tenant_app"),
    "activation": ("ffp_ray513_test_activation", "ffp_activation_app"),
    "platform": ("ffp_ray513_test_platform", "ffp_platform_app"),
}
POSTGRES_VARIABLES = {
    "admin": "FEETFORCEPLATE_TEST_ADMIN_DSN",
    "tenant": "FEETFORCEPLATE_TEST_TENANT_DSN",
    "activation": "FEETFORCEPLATE_TEST_ACTIVATION_DSN",
    "platform": "FEETFORCEPLATE_TEST_PLATFORM_DSN",
}
TARGET_OVERRIDE_VARIABLES = (
    "FEETFORCEPLATE_TEST_POSTGRES_BIND_HOST",
    "FEETFORCEPLATE_TEST_POSTGRES_PORT",
    "FEETFORCEPLATE_TEST_POSTGRES_DATABASE",
    "FEETFORCEPLATE_TEST_POSTGRES_RUNTIME_ROOT",
)
TEST_FILES = (
    "cloud/tests/test_postgres_capture_grants.py",
    "cloud/tests/test_identity_recovery_postgres_live.py",
)


def validate_target(host: str, port: int, database: str, runtime_root: Path) -> None:
    """Refuse any target outside the single authorized local test cluster."""

    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("PostgreSQL test host must be a literal loopback address") from error
    if not address.is_loopback or str(address) != HOST:
        raise ValueError("PostgreSQL test host must be exactly 127.0.0.1")
    if port != PORT:
        raise ValueError("PostgreSQL test port must be 55432")
    if database != DATABASE:
        raise ValueError("PostgreSQL test database must be ffp_ray513_test")
    if _canonical(runtime_root) != _canonical(RUNTIME_ROOT):
        raise ValueError("PostgreSQL test runtime root is fixed to its private local directory")
    lexical_root = Path(os.path.abspath(runtime_root))
    _reject_reparse_components(lexical_root)
    if "onedrive" in {part.casefold() for part in lexical_root.parts}:
        raise ValueError("PostgreSQL test runtime root must not be in OneDrive")
    canonical_root = lexical_root.resolve(strict=False)
    _reject_reparse_components(canonical_root)
    if "onedrive" in {part.casefold() for part in canonical_root.parts}:
        raise ValueError("PostgreSQL test runtime root must not be in OneDrive")
    canonical_repo = REPOSITORY_ROOT.resolve()
    if canonical_root == canonical_repo or canonical_repo in canonical_root.parents:
        raise ValueError("PostgreSQL test runtime root must stay outside the repository")


def _reject_reparse_components(path: Path) -> None:
    """Reject a reparse point before resolving away its lexical component."""

    absolute_path = Path(os.path.abspath(path))
    for candidate in (absolute_path, *absolute_path.parents):
        if _is_reparse_point(candidate):
            raise ValueError("PostgreSQL test path must not traverse a reparse point")


def _canonical(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _binary(name: str) -> Path:
    path = POSTGRES_BIN / f"{name}.exe"
    if not path.is_file():
        raise RuntimeError(f"required PostgreSQL 16 binary is missing: {name}.exe")
    return path


def _safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("PG"):
            environment.pop(name, None)
    return environment


def _run(
    arguments: list[str],
    *,
    operation: str,
    environment: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str | None]:
    try:
        output_options = (
            {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if not capture_output else {}
        )
        result = subprocess.run(
            arguments,
            input=input_text,
            text=True,
            capture_output=capture_output,
            check=False,
            env=environment if environment is not None else _safe_environment(),
            **output_options,
        )
    except OSError as error:
        raise RuntimeError(f"{operation} could not start") from error
    if check and result.returncode != 0:
        detail = result.stderr.strip().splitlines()[:3]
        safe_detail = " ".join(detail)[:500]
        for name, value in (environment or {}).items():
            if name == "PGPASSWORD" and value:
                safe_detail = safe_detail.replace(value, "<redacted>")
        safe_detail = re.sub(
            r"(?i)(password\s+)(?:'[^']*'|\S+)", r"\1<redacted>", safe_detail
        )
        suffix = f": {safe_detail}" if safe_detail else ""
        raise RuntimeError(
            f"{operation} failed with exit code {result.returncode}{suffix}"
        )
    return result


def _verify_acl(path: Path, *, action: str = "verify") -> None:
    _verify_acls((path,), action=action)


def _verify_acls(paths: tuple[Path, ...] | list[Path], *, action: str = "verify") -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if powershell is None or not ACL_SCRIPT.is_file():
        raise RuntimeError("the private PostgreSQL ACL verifier is unavailable")
    if not paths or any(";" in str(path) for path in paths):
        raise RuntimeError("private PostgreSQL ACL paths are invalid")
    _run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(ACL_SCRIPT),
         "-Action", action, "-Path", ";".join(map(str, paths))],
        operation="private PostgreSQL ACL verification",
    )


def _ensure_private_root() -> None:
    validate_target(HOST, PORT, DATABASE, RUNTIME_ROOT)
    if os.name != "nt":
        raise RuntimeError("this PostgreSQL test environment is Windows-only")
    if RUNTIME_ROOT.exists() or RUNTIME_ROOT.is_symlink():
        raise RuntimeError("private PostgreSQL runtime already exists; refusing to overwrite it")
    RUNTIME_ROOT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_ROOT.mkdir()
    _verify_acl(RUNTIME_ROOT, action="set")
    for path in (DATA_ROOT, PRIVATE_ROOT, LOG_ROOT):
        path.mkdir()
    _verify_acls((DATA_ROOT, PRIVATE_ROOT, LOG_ROOT))


def _require_private_root() -> None:
    validate_target(HOST, PORT, DATABASE, RUNTIME_ROOT)
    for path in (RUNTIME_ROOT, DATA_ROOT, PRIVATE_ROOT, LOG_ROOT):
        if not path.is_dir() or path.is_symlink() or _is_reparse_point(path):
            raise RuntimeError("private PostgreSQL runtime contains a missing or unsafe directory")
    if not CREDENTIALS_PATH.is_file() or CREDENTIALS_PATH.is_symlink():
        raise RuntimeError("private PostgreSQL credentials are missing or unsafe")
    _verify_acls((RUNTIME_ROOT, DATA_ROOT, PRIVATE_ROOT, LOG_ROOT, CREDENTIALS_PATH))


def _load_credentials() -> dict[str, str]:
    try:
        credentials = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("private PostgreSQL credentials cannot be read") from error
    names = {"admin", *APPLICATION_ROLES}
    if not isinstance(credentials, dict) or set(credentials) != names:
        raise RuntimeError("private PostgreSQL credentials have an invalid role set")
    if any(not isinstance(credentials[name], str) or len(credentials[name]) < 40 for name in names):
        raise RuntimeError("private PostgreSQL credentials are invalid")
    if len({credentials[name] for name in names}) != len(names):
        raise RuntimeError("PostgreSQL test roles must use distinct credentials")
    return credentials


def _dsn(role: str, password: str) -> str:
    return f"postgresql://{role}:{quote(password, safe='')}@{HOST}:{PORT}/{DATABASE}"


def _port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            listener.bind((HOST, PORT))
        except OSError:
            return False
    return True


def _pg_ctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    capture_output = "start" not in arguments
    return _run(
        [str(_binary("pg_ctl")), "--pgdata", str(DATA_ROOT), *arguments],
        operation="isolated PostgreSQL pg_ctl",
        check=check,
        capture_output=capture_output,
    )


def _is_running() -> bool:
    return _pg_ctl("status", check=False).returncode == 0


def _safe_pg_environment(password: str) -> dict[str, str]:
    environment = _safe_environment()
    environment["PGPASSWORD"] = password
    environment["PGCONNECT_TIMEOUT"] = "5"
    return environment


def _psql(
    database: str,
    password: str,
    *,
    sql: str | None = None,
    file: Path | None = None,
    query: str | None = None,
) -> str:
    arguments = [
        str(_binary("psql")), "--no-psqlrc", "--no-password", "--set", "ON_ERROR_STOP=1",
        "--host", HOST, "--port", str(PORT), "--username", ADMIN_ROLE, "--dbname", database,
    ]
    if file is not None:
        arguments.extend(("--file", str(file)))
    elif query is not None:
        arguments.extend(
            ("--tuples-only", "--no-align", "--field-separator", "|", "--command", query)
        )
    else:
        arguments.extend(("--file", "-"))
    result = _run(
        arguments,
        operation="isolated PostgreSQL SQL operation",
        environment=_safe_pg_environment(password),
        input_text=sql,
    )
    return result.stdout.strip()


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _initialize_cluster_files(credentials: dict[str, str]) -> None:
    password_file = PRIVATE_ROOT / "initdb-password.txt"
    with password_file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(credentials["admin"] + "\n")
    _verify_acl(password_file)
    try:
        _run(
            [
                str(_binary("initdb")), "--pgdata", str(DATA_ROOT),
                "--username", ADMIN_ROLE, "--pwfile", str(password_file),
                "--auth-local=scram-sha-256", "--auth-host=scram-sha-256",
                "--encoding=UTF8", "--locale=C", "--no-instructions",
            ],
            operation="isolated PostgreSQL initdb",
        )
    finally:
        password_file.unlink(missing_ok=True)
    with (DATA_ROOT / "postgresql.conf").open("a", encoding="utf-8") as stream:
        stream.write(
            "\nlisten_addresses = '127.0.0.1'\n"
            "port = 55432\n"
            "password_encryption = 'scram-sha-256'\n"
            "ssl = off\n"
        )
    (DATA_ROOT / "pg_hba.conf").write_text(
        "local all all scram-sha-256\n"
        "host all all 127.0.0.1/32 scram-sha-256\n"
        "host all all ::1/128 reject\n"
        "host all all 0.0.0.0/0 reject\n"
        "host all all ::/0 reject\n",
        encoding="utf-8",
    )


def _start_cluster(*, verify_database: bool = True) -> None:
    if _is_running():
        if verify_database:
            _validate_server()
        return
    if not _port_is_free():
        raise RuntimeError("127.0.0.1:55432 is occupied; no PostgreSQL process was started")
    _pg_ctl(
        "--log", str(LOG_ROOT / "postgres.log"),
        "--options", f"-h {HOST} -p {PORT}", "--wait", "start",
    )
    if verify_database:
        _validate_server()


def _create_roles_and_database(credentials: dict[str, str]) -> None:
    admin_password = credentials["admin"]
    database_exists = _psql(
        "postgres", admin_password,
        query=f"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DATABASE}')",
    )
    if database_exists != "t":
        _psql("postgres", admin_password, sql=f"CREATE DATABASE {DATABASE} TEMPLATE template0;")
    for name, (role, _membership) in APPLICATION_ROLES.items():
        exists = _psql(
            "postgres", admin_password,
            query=f"SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')",
        )
        verb = "ALTER" if exists == "t" else "CREATE"
        _psql(
            "postgres", admin_password,
            sql=(f"{verb} ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                 "INHERIT NOBYPASSRLS NOREPLICATION "
                 f"PASSWORD {_sql_literal(credentials[name])};"),
        )
    backup_exists = _psql(
        "postgres", admin_password,
        query="SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ffp_seed_backup')",
    )
    backup_verb = "ALTER" if backup_exists == "t" else "CREATE"
    _psql(
        "postgres", admin_password,
        sql=(f"{backup_verb} ROLE ffp_seed_backup NOLOGIN NOSUPERUSER NOCREATEDB "
             "NOCREATEROLE INHERIT BYPASSRLS NOREPLICATION;"),
    )


def _apply_migrations(credentials: dict[str, str]) -> None:
    admin_password = credentials["admin"]
    _psql(
        DATABASE, admin_password,
        sql="CREATE TABLE IF NOT EXISTS public.ffp_ray513_test_migrations (name text PRIMARY KEY);",
    )
    migrations = sorted((REPOSITORY_ROOT / "cloud" / "migrations").glob("*.sql"))
    if not migrations:
        raise RuntimeError("committed PostgreSQL migrations are missing")
    for migration in migrations:
        applied = _psql(
            DATABASE, admin_password,
            query=("SELECT EXISTS (SELECT 1 FROM public.ffp_ray513_test_migrations "
                   f"WHERE name = {_sql_literal(migration.name)})"),
        )
        if applied == "t":
            continue
        _psql(DATABASE, admin_password, file=migration)
        _psql(
            DATABASE, admin_password,
            sql=("INSERT INTO public.ffp_ray513_test_migrations(name) VALUES "
                 f"({_sql_literal(migration.name)});"),
        )
    grants = "\n".join(
        f"GRANT {membership} TO {role} WITH INHERIT TRUE;"
        for role, membership in APPLICATION_ROLES.values()
    )
    _psql(DATABASE, admin_password, sql=grants)


def _create_cluster() -> None:
    validate_target(HOST, PORT, DATABASE, RUNTIME_ROOT)
    if not _port_is_free():
        raise RuntimeError("127.0.0.1:55432 is occupied; private cluster was not created")
    for name in ("initdb", "pg_ctl", "postgres", "psql"):
        _binary(name)
    _ensure_private_root()
    credentials = {
        name: secrets.token_urlsafe(48) for name in ("admin", *APPLICATION_ROLES)
    }
    with CREDENTIALS_PATH.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(credentials, stream, sort_keys=True)
        stream.write("\n")
    _verify_acl(CREDENTIALS_PATH)
    _initialize_cluster_files(credentials)
    _start_cluster(verify_database=False)
    try:
        _create_roles_and_database(credentials)
        _apply_migrations(credentials)
        summary = _validate_role_contract(credentials)
    except Exception:
        if _is_running():
            _pg_ctl("--mode", "fast", "--wait", "stop")
        raise
    print(json.dumps({"status": "private_postgres_ready", **summary}, sort_keys=True))


def _resume_incomplete_cluster() -> None:
    credentials = _load_credentials()
    _start_cluster(verify_database=False)
    _validate_server(database="postgres")
    try:
        _create_roles_and_database(credentials)
        _apply_migrations(credentials)
        summary = _validate_role_contract(credentials)
    except Exception:
        if _is_running():
            _pg_ctl("--mode", "fast", "--wait", "stop")
        raise
    print(json.dumps({"status": "private_postgres_ready", "resumed": True, **summary}, sort_keys=True))


def _role_dsns(credentials: dict[str, str]) -> dict[str, str]:
    values = {
        POSTGRES_VARIABLES["admin"]: _dsn(ADMIN_ROLE, credentials["admin"]),
        POSTGRES_VARIABLES["tenant"]: _dsn(
            APPLICATION_ROLES["tenant"][0], credentials["tenant"]
        ),
        POSTGRES_VARIABLES["activation"]: _dsn(
            APPLICATION_ROLES["activation"][0], credentials["activation"]
        ),
        POSTGRES_VARIABLES["platform"]: _dsn(
            APPLICATION_ROLES["platform"][0], credentials["platform"]
        ),
    }
    roles: set[str | None] = set()
    passwords: set[str | None] = set()
    for dsn in values.values():
        endpoint = urlparse(dsn)
        try:
            host = ipaddress.ip_address(endpoint.hostname or "")
        except ValueError as error:
            raise RuntimeError("PostgreSQL test DSN must use a literal loopback host") from error
        if str(host) != HOST or not host.is_loopback:
            raise RuntimeError("PostgreSQL test DSN escaped 127.0.0.1")
        if endpoint.port != PORT or endpoint.path != f"/{DATABASE}":
            raise RuntimeError("PostgreSQL test DSN escaped the fixed port or database")
        roles.add(endpoint.username)
        passwords.add(endpoint.password)
    if len(values) != 4 or len(roles) != 4 or len(passwords) != 4:
        raise RuntimeError("four distinct local PostgreSQL test roles and passwords are required")
    return values


def _psql_as(role: str, password: str, query: str, *, database: str = DATABASE) -> str:
    arguments = [
        str(_binary("psql")), "--no-psqlrc", "--no-password", "--tuples-only",
        "--no-align", "--field-separator", "|", "--host", HOST, "--port", str(PORT),
        "--username", role, "--dbname", database, "--command", query,
    ]
    return _run(
        arguments,
        operation="isolated PostgreSQL role check",
        environment=_safe_pg_environment(password),
    ).stdout.strip()


def _validate_server(*, database: str = DATABASE) -> None:
    credentials = _load_credentials()
    if not _is_running():
        raise RuntimeError("private PostgreSQL cluster is stopped")
    endpoint = _psql_as(
        ADMIN_ROLE,
        credentials["admin"],
        "SELECT host(inet_server_addr()) || '|' || inet_server_port()::text || '|' || current_database()",
        database=database,
    )
    if endpoint != f"{HOST}|{PORT}|{database}":
        raise RuntimeError(
            "PostgreSQL server identity does not match the isolated test target "
            f"(received {endpoint or '<empty>'})"
        )


def _validate_role_contract(credentials: dict[str, str]) -> dict[str, object]:
    _validate_server()
    roles = {"admin": ADMIN_ROLE}
    roles.update({name: role for name, (role, _membership) in APPLICATION_ROLES.items()})
    role_facts: dict[str, dict[str, object]] = {}
    for name, role in roles.items():
        facts = _psql_as(
            role,
            credentials[name],
            "SELECT current_user || '|' || current_database() || '|' || "
            "host(inet_server_addr()) || '|' || inet_server_port()::text",
        )
        if facts != f"{role}|{DATABASE}|{HOST}|{PORT}":
            raise RuntimeError("a PostgreSQL test role resolved outside its expected target")
        superuser, bypass_rls = _psql_as(
            ADMIN_ROLE, credentials["admin"],
            f"SELECT rolsuper || '|' || rolbypassrls FROM pg_roles WHERE rolname = '{role}'",
        ).split("|")
        expected = ("true", "true") if name == "admin" else ("false", "false")
        if (superuser, bypass_rls) != expected:
            raise RuntimeError("PostgreSQL test role has unexpected superuser or RLS bypass privileges")
        role_facts[name] = {
            "role": role,
            "host": HOST,
            "port": PORT,
            "database": DATABASE,
            "superuser": superuser == "true",
            "bypass_rls": bypass_rls == "true",
        }
    rls_rows = _psql_as(
        ADMIN_ROLE, credentials["admin"],
        "SELECT n.nspname || '.' || c.relname || '|' || c.relrowsecurity || '|' || "
        "c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE (n.nspname,c.relname) IN (('screening','capture_grants'), "
        "('screening','upload_migration_permits'), ('ops','capture_authorization_audit')) "
        "ORDER BY n.nspname,c.relname",
    ).splitlines()
    expected_rls = {
        "ops.capture_authorization_audit|true|true",
        "screening.capture_grants|true|true",
        "screening.upload_migration_permits|true|true",
    }
    if set(rls_rows) != expected_rls:
        raise RuntimeError("RAY-513 PostgreSQL authorization tables do not enforce RLS")
    memberships = {
        name: _psql_as(
            ADMIN_ROLE, credentials["admin"],
            f"SELECT pg_has_role('{role}','{membership}','MEMBER')",
        )
        for name, (role, membership) in APPLICATION_ROLES.items()
    }
    if any(value != "t" for value in memberships.values()):
        raise RuntimeError("PostgreSQL application roles are missing their expected grants")
    return {
        "host": HOST,
        "port": PORT,
        "database": DATABASE,
        "roles": role_facts,
        "rls_tables": sorted(rls_rows),
        "application_role_memberships": memberships,
        "credentials_included": False,
    }


def _live_tests() -> int:
    credentials = _load_credentials()
    summary = _validate_role_contract(credentials)
    dsn_values = _role_dsns(credentials)
    test_environment = os.environ.copy()
    test_environment.update(dsn_values)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *TEST_FILES],
            cwd=REPOSITORY_ROOT,
            env=test_environment,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("RAY-513 PostgreSQL live tests could not start") from error
    output = result.stdout + result.stderr
    for secret in (*credentials.values(), *dsn_values.values()):
        output = output.replace(secret, "<redacted>")
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_path = LOG_ROOT / f"live-tests-{run_stamp}.log"
    with evidence_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(output)
    print(json.dumps({"role_check": summary, "test_log": evidence_path.name}, sort_keys=True))
    print(output, end="")
    return result.returncode


def _stop_cluster() -> None:
    if not _is_running():
        print(json.dumps({"status": "private_postgres_already_stopped"}, sort_keys=True))
        return
    _pg_ctl("--mode", "fast", "--wait", "stop")
    print(json.dumps({"status": "private_postgres_stopped", "data_preserved": True}, sort_keys=True))


def _status() -> None:
    print(json.dumps({
        "status": "running" if _is_running() else "stopped",
        "host": HOST, "port": PORT, "database": DATABASE,
        "runtime_root": str(RUNTIME_ROOT), "credentials_included": False,
    }, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    if os.name != "nt":
        print("this PostgreSQL test environment is Windows-only", file=sys.stderr)
        return 2
    if any(os.environ.get(name) for name in TARGET_OVERRIDE_VARIABLES):
        print("PostgreSQL test target overrides are refused", file=sys.stderr)
        return 2
    action = argv[0] if argv else ""
    try:
        if action != "prepare":
            _require_private_root()
        if action == "prepare":
            _create_cluster()
        elif action == "resume":
            _resume_incomplete_cluster()
        elif action == "start":
            _start_cluster()
            print(json.dumps({"status": "private_postgres_running", "host": HOST, "port": PORT}))
        elif action == "stop":
            _stop_cluster()
        elif action == "status":
            _status()
        elif action == "live-tests":
            return _live_tests()
        else:
            print("expected prepare, start, stop, status, or live-tests", file=sys.stderr)
            return 2
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
