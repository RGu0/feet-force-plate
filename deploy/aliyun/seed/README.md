# Aliyun seed-pilot deployment

This directory installs a controlled integration endpoint, not a production
commercial ingress. Public traffic reaches Nginx TLS on 7443; Uvicorn listens
only on `127.0.0.1:8743`; PostgreSQL listens only on loopback. Formal customer
rollout still requires a domain, public-CA certificate, port 443, customer
onboarding evidence, and the applicable compliance review.

## Required host layout

- `/opt/feetforceplate/releases/<commit-sha>`: immutable application release;
- `/opt/feetforceplate/app`: symlink to the current release;
- `/etc/feetforceplate/seed.env`: service-user-owned mode `0600` secrets;
- `/etc/feetforceplate/tls`: Nginx-readable certificate and private key;
- `/var/lib/feetforceplate/objects`: service-user-owned mode `0700` objects;
- `/var/lib/feetforceplate/backups`: service-user-owned mode `0700` backups.

Create the dedicated system user with no interactive login, install PostgreSQL
and Nginx from the OS package manager, and ensure 5432 and 8743 are not admitted
by the cloud security group or host firewall. The migration role applies
`0001`, `0002`, then `0003`; application LOGIN roles are created by
`postgresql-role-grants.sql` using `psql` variables supplied outside shell
history. No application role is an owner, superuser, or `BYPASSRLS` role.

For the RAY-99 upgrade, deploy the unverified-session-hold release and verify
migrations 0009 (hold) and 0010 (report copy) before controlled identity
recovery migration 0011. The release installer refuses migration 0011 when the hold table is absent. A successful
installer run does not itself establish the real incident hold or prove a
backup restore; record those as separate acceptance evidence.

After the role grants the installer applies, in order: 0011 controlled
identity recovery, 0012 terminal activation, 0013 insole inventory, 0014
recovery-bound migration permits, 0015 terminal data-plane projection (every
install), 0016 insole session archive (every install), and 0017 subject sync
(RAY-907; once, while `subject.subjects.revision` is absent). 0017 backfills a
revision for every existing subject in creation order and adds the revision
triggers, the name lookup column and the tag tables; it is additive but not
reversible by the installer, so take a backup and pass `run-restore-drill.sh`
before deploying it. `backup.sh` records the applied list in
`metadata.json` `schema_versions`.

The host cannot reach github.com. `deploy-sales-inventory-release.sh` downloads
the foundation wheel on the operator machine, checks it against `uv.lock`, and
uploads it with the archive; the installer re-checks the digest, seeds the
service user's uv cache from the uploaded wheel (`warm_foundation_wheel_cache.py`,
a loopback endpoint that serves only the locked URL, so a fresh host or a
foundation upgrade needs no prior cache), and proves the new release resolves
dependencies offline (`UV_OFFLINE=1`) before any migration. The seed and backup services run with `UV_OFFLINE=1`.

On a new Alibaba Cloud Linux host, run the reviewed prerequisite script once as
root. It is idempotent and deliberately does not stop or reconfigure the
existing 7443 process, so the later cutover remains reversible:

```bash
sudo bash deploy/aliyun/seed/host-prerequisites.sh \
  /home/rui/apps/feetforceplate-seed/tools/age-v1.3.1
```

After reviewing paths and certificate names:

```bash
sudo ./deploy/aliyun/seed/install-layout.sh /tmp/ffp-release "$RELEASE_SHA"
sudo install -o root -g root -m 0644 deploy/aliyun/seed/feetforceplate-seed.service \
  /etc/systemd/system/feetforceplate-seed.service
sudo install -o root -g root -m 0644 deploy/aliyun/seed/nginx-feetforceplate-seed.conf \
  /etc/nginx/conf.d/feetforceplate-seed.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now feetforceplate-seed.service nginx
```

Readiness returns only `postgres` and `object_store` states. Logs contain method,
URI, status, byte count, remote address and request ID; they exclude request
bodies and Authorization headers. Never put DSNs, passwords, activation codes,
private keys, raw identities, or full hardware serials in deployment evidence.

## Diagnostic package purge and OSS backstop (RAY-927)

The installer applies `0018_terminal_diagnostics.sql` (RAY-802) once, while
`ops.terminal_diagnostics` is absent, and grants the backup role `SELECT` on it.
Packages are kept 30 days from upload (`expires_at`).

`feetforceplate-diagnostics-purge.timer` runs
`feetforceplate-diagnostics-purge.service` once a day (03:30 host time plus up
to 20 minutes; `Persistent=true` catches up a missed run after downtime). The
service runs as `feetforceplate` with `seed.env`, offline from the service uv
cache like the backup service, and executes
`./dev run python -m cloud.terminal_diagnostics.purge`. It deletes the content
of every expired package and keeps the row as a tombstone with `deleted_at`; an
interrupted run is safe to repeat. Its stdout is only `{"purged": <count>}`;
the journal also gets `uv sync` progress lines, and on failure a Python
traceback that holds no DSN or credential but may name an object key (which
contains a tenant UUID), so read a failed run's journal before quoting it in
evidence. A start timeout of 30 minutes stops a hung run from blocking the next
day's. The purge's `DeleteObject` needs the OSS role grant below; one manual
run (below) after each first install proves it, as nothing alerts on a failed
nightly run. `install-seed-release.sh` installs both units, enables and starts
the timer. To run it once by hand and read the result:

```bash
sudo systemctl start feetforceplate-diagnostics-purge.service
sudo journalctl -u feetforceplate-diagnostics-purge.service -n 5 --no-pager
systemctl list-timers feetforceplate-diagnostics-purge.timer --no-pager
```

The diagnostics smoke (`scripts/run_ray802_diagnostics_smoke.py`) can only see
HTTP answers; it records the run's `ticket_reference`, and the audit rows the
support list/read and the two refusals produced are checked read-only on the
host with that value:

```bash
sudo -u postgres psql -d feetforceplate_seed -Atc "select action, coalesce(details->>'actor_kind',''), coalesce(details->>'reason',''), count(*) from ops.access_audit_events where details->>'ticket_reference' = '<ticket_reference>' group by 1,2,3 order by 1,2,3"
# expect diagnostics.deny|platform|role_unauthorized|1, diagnostics.deny|terminal|terminal_credential|1,
#        diagnostics.list|platform||1, diagnostics.read|platform||1
```

### OSS role grant for `diagnostics/`

With `FEETFORCEPLATE_OBJECT_BACKEND=aliyun-oss` the service's ECS RAM role
needs, on `acs:oss:*:*:<bucket>/diagnostics/*` in addition to its existing
`tenants/*` grant:

- `oss:PutObject` for the upload;
- `oss:GetObject` for the immutable-put pre-check (`HeadObject`, which OSS
  authorizes as `GetObject`) and the support read;
- `oss:DeleteObject` for the purge.

No list action is needed; keep the actions to these three rather than a
wildcard.

Without this grant the upload fails with 500 `E-CLD-500` (OSS 403 `AccessDenied` on
`HeadObject`). The simplest form adds the prefix to the statement that already
grants these actions on `tenants/*`:

```json
{
  "Effect": "Allow",
  "Action": ["oss:PutObject", "oss:GetObject", "oss:DeleteObject"],
  "Resource": [
    "acs:oss:*:*:<bucket>/tenants/*",
    "acs:oss:*:*:<bucket>/diagnostics/*"
  ]
}
```

The diagnostics smoke (above) proves the upload and read; a manual purge run
proves the delete.

### OSS lifecycle backstop

The purge is the mechanism. With the OSS backend the bucket also carries a
lifecycle backstop for content the purge missed (for example while the timer
was broken):

- one rule, prefix `diagnostics/` only, current-version objects expire 31 days
  after last modification: not earlier than the 30-day retention, with a day of
  margin for time zones and clock skew;
- set by the operator in the Aliyun OSS console (bucket, Data Management,
  Lifecycle). Before saving, review every existing rule on the bucket: none may
  cover `diagnostics/` with a shorter current-version expiry (an empty-prefix
  whole-bucket rule counts; its noncurrent-version expiry is expected, see
  below) and the new rule must not cover any other prefix. On the integration
  bucket, which has a whole-bucket rule, the first save failed with
  `InvalidRequest` (ecCode `0014-00000084`); it saved only with "allow prefix
  overlap" (允许前缀重叠) on;
- record only the rule's description (prefix, action, days, the review of
  existing rules) in evidence; never an AccessKey, STS token or console
  credential. The rule itself needs no change to the ECS RAM role.

The integration bucket has versioning enabled. There a purge or expiry
`DeleteObject` only adds a delete marker and leaves the content as a noncurrent
version; the content is removed by a noncurrent-version rule. On the
integration bucket that is the existing whole-bucket rule: noncurrent versions
are deleted 3 days after becoming noncurrent and expired delete markers are
removed. So the `diagnostics/` rule sets current-version expiry only, and a
purged package's content stays recoverable for about 3 more days. A versioned
bucket without such a rule keeps purged content indefinitely.

With the filesystem backend there is no backstop; the purge alone deletes
content under `/var/lib/feetforceplate/objects/diagnostics/`.
