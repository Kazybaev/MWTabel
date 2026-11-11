# WAHA production reports to parents

The parent-report channel is separate from both the WAHA test-recipient queue
and the existing Dify/Meta workflow. Creating a batch only stores a draft. An
administrator must inspect the students, masked parent numbers, generated text,
and skipped reasons, then explicitly confirm the batch before any worker can
send it.

## Eligibility and duplicate protection

- The report month must have lessons. Draft preparation and confirmation are
  allowed on any date; they are not restricted to the group's latest lesson
  date.
- At least one lesson record for the student must exist in the report month;
  the record does not have to be from the latest lesson.
- The destination is `StudentProfile.parent_phone`, never the test recipient.
- An existing Dify/Meta dispatch or active Dify batch, a WAHA test attempt, or a
  previous WAHA parent batch does not block preparing or confirming another
  parent batch. This allows duplicate sends, including when a previous WAHA
  result is accepted, failed, or unknown; inspect delivery history carefully
  before confirming a repeated batch. Unknown WAHA results are never retried
  automatically.
- Eligibility and cross-channel conflict checks run again during confirmation.
  Repeated WAHA parent batches are intentionally not deduplicated and can send
  the same report more than once.
- WAHA `accepted` means the HTTP request was accepted, not that WhatsApp
  delivered the message.
- The selected recipient rule is every otherwise-eligible active student with
  a valid parent phone. The application does not store parent WhatsApp opt-in.
  Confirm your legal and WhatsApp-policy basis to contact recipients before
  any live batch; unsolicited messages may lead to complaints or account
  restrictions.

## Feature flags and explicit activation

Production sending is disabled by default. Keep these values false until the
account, opt-in/consent process, operational limits, and recipient data have
been reviewed:

```text
WAHA_PARENT_REPORTS_ENABLED=false
WAHA_PARENT_WORKER_ENABLED=false
```

Draft preparation is available while sending is disabled. Confirmation and
worker startup both require the two flags to be true, plus the WAHA API key
configuration set specifically for production. Production has a separate
WAHA service, API key/hash, Dashboard password, `default` session, and Docker
volume; it must use a separately authorized WhatsApp account. Never reuse the
test pilot's key, QR login, or session volume.

Configure these production-only secrets in the deployment secret store:

```text
WAHA_PARENT_API_KEY=<unique client API key>
WAHA_PARENT_API_KEY_HASH=sha512:<hash of that same key>
WAHA_PARENT_DASHBOARD_PASSWORD=<unique Dashboard password>
```

After independent operational approval and provisioning the separate
WhatsApp account, start the production WAHA instance:

```bash
docker compose --profile waha-parent up -d waha-parent
```

On Ubuntu, set `WAHA_PARENT_IMAGE` to a version-pinned image verified for the
server's CPU architecture first. The ARM image pinned for the local test pilot
may not run on an x86_64 production host. See
[the Ubuntu deployment checklist](./production-deployment-ubuntu.md).

Then start the worker explicitly:

```bash
docker compose --profile waha-parent up -d waha-parent-worker
```

The worker uses the existing WAHA session (`default` for WAHA Core), a
configurable interval of at least two seconds between requests, and processes
only confirmed queue items. Before claiming work it checks that the WAHA
session is `WORKING` and that WhatsApp's reachout timelock is inactive. The
worker pauses without claiming messages while the session is unavailable or
the timelock is active. WhatsApp can temporarily restrict accounts that
message too many new contacts; WAHA documents this
[reachout timelock](https://waha.devlike.pro/docs/how-to/sessions/). Do not
restart or re-pair the account to try to bypass such a restriction. Do not run
multiple production workers for the same WAHA session. HTTP 5xx, timeouts, and
stale `processing` items become `unknown`; they are never requeued
automatically.

No production batches are created or sent as part of development or deployment.
