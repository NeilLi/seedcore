# Local research report synchronization

`local_research_sync.py` fetches one private Google Doc through the Drive API
and prepares a local review candidate. A macOS LaunchAgent can run it unattended.
It needs no LLM, does not change document sharing, and never commits or pushes.
The report remains external, unverified evidence; it cannot qualify physics,
promote a model, or authorize runtime execution.

Candidates and status live outside Git at
`~/Library/Application Support/SeedCore/research-sync/`. The directory is mode
0700 and candidate/status files are 0600. The worker refuses a state directory
inside any Git checkout. Only an explicit approval of the candidate's SHA-256
copies its exact contents into `docs/development/reports/embodied_ai_research_report.md`.
Review that Git diff before publishing through your normal reviewed Git workflow.

## Manual use on an intermittently connected Mac

Use manual runs for this Mac; installing the scheduler is optional. After the
one-time private access setup below, connect to the internet and run:

```bash
cd /Users/ningli/project/seedcore
.venv/bin/python scripts/docs/local_research_sync.py \
  --credentials "$HOME/Library/Application Support/SeedCore/research-sync/google/application_default_credentials.json" run
```

This fetches once and exits. It works without a LaunchAgent and runs immediately
even if this week's sync already succeeded. It does not install a background
job, commit, or push. Fetching Google Docs requires an internet connection and
working OAuth credentials; it cannot download new content while offline.

You can inspect an already saved candidate without internet access:

```bash
.venv/bin/python scripts/docs/local_research_sync.py status
.venv/bin/python scripts/docs/local_research_sync.py review
```

Applying an approved candidate also works offline, provided the latest fetch
succeeded and the repository baseline still matches. A failed offline fetch
preserves the candidate but blocks applying it until a successful fetch. If
three failed attempts suspend fetching, reconnect, run `resume`, then `run`
again as described below. No scheduler is currently installed.

## Private access setup

Use Python 3.11+ on macOS and install the pinned local dependencies:

```bash
.venv/bin/python -m pip install -r scripts/docs/requirements-local.txt
```

Enable the Google Drive API in a Google Cloud project, configure its OAuth
consent screen, and create/download a **Desktop app OAuth client** JSON. Authorize
an account that can view and export the source document. Keep the document
private. The `drive.readonly` grant permits reading that account's accessible
Drive files; the worker itself requests only the configured document ID. Use a
dedicated account with access only to the intended source if you need a narrower
account boundary.

Create isolated credentials so this job does not replace your existing Google
Cloud login. Substitute the actual client JSON path; run the login interactively
to review Google's consent screen:

```bash
RESEARCH_GOOGLE_CONFIG="$HOME/Library/Application Support/SeedCore/research-sync/google"
mkdir -p "$RESEARCH_GOOGLE_CONFIG"
chmod 700 "$RESEARCH_GOOGLE_CONFIG"
CLOUDSDK_CONFIG="$RESEARCH_GOOGLE_CONFIG" gcloud auth application-default login \
  --client-id-file="/absolute/path/to/desktop-oauth-client.json" \
  --scopes="https://www.googleapis.com/auth/drive.readonly"
chmod 600 "$RESEARCH_GOOGLE_CONFIG/application_default_credentials.json"
RESEARCH_CREDENTIALS="$RESEARCH_GOOGLE_CONFIG/application_default_credentials.json"
```

The credential JSON contains a refresh token: keep it and the OAuth client JSON
outside Git. Pass `--credentials` explicitly to use the isolated file; the CLI's
fallback is the existing `~/.config/gcloud/application_default_credentials.json`.
The worker refreshes tokens in memory and never rewrites credentials or logs
provider response bodies. OAuth consent configurations that expire refresh
tokens require reauthorization; see Google's
[local ADC setup](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).

Verify a real private export:

```bash
.venv/bin/python scripts/docs/local_research_sync.py --credentials "$RESEARCH_CREDENTIALS" check
```

Then use the manual `run` command above. Only if you later want automatic
scheduling, install the optional job:

```bash
.venv/bin/python scripts/docs/local_research_sync.py --credentials "$RESEARCH_CREDENTIALS" install
```

`check` prints source metadata and byte count, without saving document content.
`install` fetches a candidate and requires an actual successful export before
writing or loading `~/Library/LaunchAgents/ai.seedcore.research-sync.plist`.
The plist contains paths, not credential contents. It uses the current Python
environment and checkout by absolute path; reinstall if either moves.

As of 2026-10-07, the existing local OAuth credentials failed to refresh. No live
private export has been validated and no LaunchAgent has been installed. The
indexed report is a pending placeholder. Complete the isolated authorization
above before activation; changing the document to public is unnecessary.

## Schedule, review, and recovery

The LaunchAgent checks hourly and on login. A successful sync satisfies the
weekly period beginning Monday at 03:00 UTC (10:00 Bangkok). If the Mac was
asleep or logged out, the next run catches up. This is a user-session job, so it
does not promise execution at the exact scheduled minute or while logged out.
See Apple's [LaunchAgent documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

Run these commands from the repository root; global options precede the command:

```bash
# Fetch now, even when this week's scheduled fetch already succeeded.
.venv/bin/python scripts/docs/local_research_sync.py --credentials "$RESEARCH_CREDENTIALS" run
.venv/bin/python scripts/docs/local_research_sync.py status
# Displays private source content locally as a diff, plus the approval digest.
.venv/bin/python scripts/docs/local_research_sync.py review
.venv/bin/python scripts/docs/local_research_sync.py apply --approve-sha256 REVIEWED_SHA256
git diff -- docs/development/reports/embodied_ai_research_report.md
```

Replace `REVIEWED_SHA256` with the digest shown by `review`. Applying requires an
exact digest match, an unchanged repository baseline, and a successful latest
fetch. A newer candidate requires another review. Identical content preserves
the candidate and timestamp. A source revert removes an obsolete pending
candidate. Private candidates are never uploaded as CI artifacts.

Failures preserve the last candidate but block applying it until a successful
fetch. After three consecutive failures, the worker suspends fetching. Repair
access first, then reset the counter and verify:

```bash
.venv/bin/python scripts/docs/local_research_sync.py resume
.venv/bin/python scripts/docs/local_research_sync.py --credentials "$RESEARCH_CREDENTIALS" run
# Stop scheduling; retain credentials and candidates for deliberate cleanup.
.venv/bin/python scripts/docs/local_research_sync.py uninstall
```

Inspect `status` and the local `agent.log` for diagnostics. Logs exclude document
content and tokens; they are not automatically rotated. Export requests have
30-second timeouts, and a CLI invocation has a three-minute execution limit.
Overlapping operations use a local file lock.

## Validation and CI

The private client uses the official
[Drive export API](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export)
with [Markdown export](https://developers.google.com/workspace/drive/api/guides/ref-export-formats).
It rejects redirects without forwarding the bearer token and checks document
identity, type, export permission, and version before and after export. HTML,
binary data, invalid UTF-8, empty or oversized exports, and documents changed
during export fail before candidate replacement. Downloads are capped at 10 MiB.
External links and images remain references, not archived assets.

`.github/workflows/sync_research_report.yml` now runs only manually triggered
offline tests with read-only repository permissions. It has no weekly cloud
fetch, write token, or auto-commit step. The unit-tests workflow also runs the
offline suite. Normal reviewed publication uses the repository's usual CI and
branch policies.

```bash
python3 -m unittest discover -s tests -p 'test_*research*.py'
```

Tests cover export failures, version changes, credential redirect isolation,
candidate integrity, stale baselines, explicit approval, failure suspension,
scheduling, and installation preflight. They use mocked Drive responses; passing
them does not demonstrate that the live document or OAuth grant is accessible.

`sync_research_report.py` remains a manual public-export utility using only the
standard library. It is not called by the scheduler. Running it explicitly
writes its chosen output directly; use `--output` outside Git for a review copy.
Its default Markdown mode preserves exported structure; `--format txt` stores
plain text in a fenced block and cannot restore native formatting.
