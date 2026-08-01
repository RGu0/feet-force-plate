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
