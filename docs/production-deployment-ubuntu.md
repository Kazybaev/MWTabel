# Ubuntu production deployment

This is a deployment checklist, not authorization to start sending reports.
It describes the current Docker Compose deployment; the production host is
not accessible from the development workspace, so no remote changes are made
by these instructions.

## Before connecting a server

Collect these values without posting them in chat:

- Ubuntu release, CPU architecture (`uname -m`), public DNS name, and SSH
  access method.
- A separately authorized WhatsApp account for parent reports.
- Production database, Django `SECRET_KEY`, Dify API key, and separate WAHA
  API key/hash and Dashboard password.
- Existing Dify Docker network name. The default is `docker_default`; verify
  it on the target server.
- A reviewed recipient list and operational approval. The selected behavior
  is to target every otherwise-eligible student with a valid parent number;
  the app does not collect a separate parent WhatsApp opt-in. Sending without
  recipient consent may violate WhatsApp policy or local rules and may result
  in complaints or account restrictions. Verify your basis to contact the
  recipients before any live batch.

The local/test WAHA image remains pinned to ARM. For the reported Ubuntu
`x86_64` host, Docker Hub publishes WAHA `latest-2026.9.2` for `amd64`. The
production template pins that image by its amd64 manifest digest, so it does
not depend on a moving `latest` tag. If the host architecture changes, verify
the corresponding manifest before changing `WAHA_PARENT_IMAGE`.

## Prepare server and secrets

1. Install supported Docker Engine and the Docker Compose plugin. Configure
   firewall access for SSH and public HTTP/HTTPS only. WAHA Dashboard and API
   remain bound to loopback (`127.0.0.1:3002`) and must not be published by
   Nginx.
2. Provision the domain and HTTPS certificate. The checked-in Nginx config
   expects certificates under `/etc/letsencrypt/live/portalmotionweb.com/`.
   Confirm those paths and the DNS names before starting Nginx.
3. Provision the database and Dify dependency. Ensure the named external
   Docker network referenced by `DIFY_DOCKER_NETWORK` exists.
4. Copy `env.production.example` to `.env.production` on the server. Replace
   every placeholder with production values; do not use `.env.postgres-local`
   or the development database snapshot for production. Set file permissions:

   ```bash
   chmod 600 .env.production
   ```

5. Keep both `WAHA_PARENT_REPORTS_ENABLED` and `WAHA_PARENT_WORKER_ENABLED`
   set to `false`. Keep test-mode flags false as well.
6. Set `WAHA_PARENT_IMAGE` to the verified image for the host architecture.
   Create a distinct production WAHA session and retain its persistent volume;
   never copy the test account's session or QR state.

## Deploy and verify with sending disabled

From the release directory on the Ubuntu host:

```bash
ENV_FILE=.env.production docker compose --env-file .env.production config --quiet
ENV_FILE=.env.production docker compose --env-file .env.production up -d --build web nginx
ENV_FILE=.env.production docker compose --env-file .env.production exec web python manage.py migrate --check
ENV_FILE=.env.production docker compose --env-file .env.production ps
```

Verify HTTPS, login, administrator-only access, WAHA parent configuration
showing `ready=false`, and draft preparation/preview. A draft creates no WAHA
request. Do not start the `waha-parent` profile or confirm a batch as part of
this smoke test.

Before any live operation, provision and connect the separate WAHA account
through a controlled administrative tunnel. Confirm API authentication and
session health without calling `sendText`. Review real recipient data, the
message, rate, permitted contact basis, support coverage, and the manual
unknown-result procedure. Live sending requires a separate explicit
authorization; enabling both flags and starting the parent worker is a
production side effect.

## Backup and recovery

Back up the production database before each release and store an encrypted
copy off-host. Also back up and protect the production WAHA session volume;
it contains account credentials. Test restores on a separate non-production
host. Never include database dumps, session data, API keys, QR codes, or
`.env.production` in Git or chat.

The worker processes only confirmed queue entries. HTTP 5xx, timeouts, and
stale processing jobs become `unknown`, not automatic retries. Pause the
worker and manually reconcile the corresponding WAHA history before deciding
what to do with an uncertain send.
