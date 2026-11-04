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
interrupted run is safe to repeat. Its only output is `{"purged": <count>}` in
the journal: no content, object key, DSN or credential. `install-seed-release.sh`
installs both units, enables and starts the timer. To run it once by hand and
read the result:

```bash
sudo systemctl start feetforceplate-diagnostics-purge.service
sudo journalctl -u feetforceplate-diagnostics-purge.service -n 5 --no-pager
systemctl list-timers feetforceplate-diagnostics-purge.timer --no-pager
```

The purge is the mechanism. With `FEETFORCEPLATE_OBJECT_BACKEND=aliyun-oss`
the bucket also carries a lifecycle backstop for content the purge missed
(for example while the timer was broken):

- one rule, prefix `diagnostics/` only, current-version objects expire 31 days
  after last modification: not earlier than the 30-day retention, with a day of
  margin for time zones and clock skew;
- set by the operator in the Aliyun OSS console (bucket, Data Management,
  Lifecycle). Before saving, review every existing rule on the bucket: none may
  cover `diagnostics/` with a shorter expiry (an empty-prefix whole-bucket rule
  counts) and the new rule must not cover any other prefix. Note whether the
  bucket has versioning enabled: then a purge or expiry leaves a noncurrent
  version behind, which needs its own decision before the rule is saved;
- record only the rule's description (prefix, action, days, the review of
  existing rules) in evidence; never an AccessKey, STS token or console
  credential. The ECS RAM role used by the service is unchanged.

With the filesystem backend there is no backstop; the purge alone deletes
content under `/var/lib/feetforceplate/objects/diagnostics/`.
