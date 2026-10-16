# Validation scope

## Correction: attachment root cause and 1.2.2 — 2026-10-16

The 1.2.1 section below identifies two attachment defects; both are now
confirmed with confound separated:

1. The ASI backend never exposes attachment bytes to the model **during tool
   turns**, even with a freshly uploaded URL (HTTP 200, model sees only an
   attachment record). Tool-turn images therefore stay as local references and
   the protocol routes image inspection to the local helper. This 1.2.1
   behavior is correct and remains in 1.2.2.
2. The backend also **does not re-bind a previously used upload URL** to a new
   task, so the helper's no-tools nested call was failing whenever it reused a
   cached URL (16:21–16:22 helper failures). Version 1.2.2 fixes this:
   `force_fresh_upload()` (thread-local; `Conversation` uses `__slots__`)
   makes the Computer route upload fresh URLs per task while the rate-limit
   cooldown still applies.

## Computer-route task retention and image repair — 2026-10-16

Version 1.2.1 fixes two production defects found after 1.2.0:

1. Long tool conversations could pin a `<system-reminder>`-only tool turn as the
   active user request, dropping the real task from the inline prompt. The
   pinner now skips reminder-only turns and keeps searching backward for real
   user text, with a dedicated regression test. (This fix is correct and
   remains in 1.2.2.)
2. ~~Live layered probes proved the ASI/Computer backend never exposes attachment
   bytes to the model during tool turns~~ — superseded by the correction above;
   the invisible-attachment cause was cached upload URL reuse, not tool turns.

Verification on 2026-10-16 (Asia/Shanghai): all 39 offline checks pass (23
bridge, 7 computer, 3 context, 4 upload, 2 portability) plus the process
ownership script. The reminder-pinning probe now pins message 0 with the real
task text inline. Live checks against the running proxy: a no-tools image turn
correctly described a probe image (text, colors, layout); the previous failing
tool-turn image shape now drives the model to the local helper, whose real
analysis it relayed (end-to-end Read → tool_result → helper → answer). The
running directory's start/stop scripts now enforce the strict installation
ownership guard. Remaining gaps: full desktop multi-turn video production,
real long-video/audio, Cowork, and live cancellation/quota-stop behavior.

## Desktop image and task-continuity repair — 2026-10-16

Version 1.1.1 fixes a real Desktop request shape: a system token-metadata message
can follow an image-bearing Read result. The latest non-system message is now
selected for fresh attachment upload. Bounded prompts pin the latest actual user
text across tool rounds, keep common tool schemas inline, and move the complete
tool catalog into an indexed local file. Full original context remains preserved.
The local raw-context limit is 2,000,000 characters so an existing conversation
polluted by the old read loop can recover; the upstream inline budget remains
28,000 characters.

All 30 offline tests pass (22 bridge, 2 context, 4 upload, 2 portability), plus
routing/authentication checks. The fresh-image and lost-task regressions failed
before the changes and passed afterward. A real image-bearing Read result with
trailing system metadata returned HTTP 200 and described the image's actual text,
colors, grid layout and timestamps. This is transport/image evidence, not proof
of provider-internal model identity or completion of a full desktop video task.

Separate Computer-mode probes succeeded with upstream mode ASI and the advertised
Computer model route: one fixed-marker response and one valid local Read request
envelope. As of 1.2.0 the Opus mapping routes through this Computer backend in
production; the 1.2.1 section above records its live task-retention and image
behavior. Full desktop acceptance remains unverified.

## Upload-limit repair — 2026-10-16

The upstream upload endpoint returned HTTP 200 with `rate_limited: true` and no
upload URL, even for a 60-byte text fixture. The previous SDK reduced that to
`FileUploadError`; the bridge returned a generic 502. Automatically uploading
full context and every historical image made unrelated text turns fail too.

The repair retains indexed full context and historical binary attachments locally,
limits the prompt body to 28,000 characters, preserves complete system instructions,
and reports upload quotas explicitly. A native Read call is required before the
model can inspect an archived image again. Quotas are neither reset nor bypassed.

`python tests/run.py` now runs 27 unit tests (20 bridge, 1 context-budget,
4 upload-guard, 2 portability) plus the isolated routing/authentication checks.
Coverage includes the captured rate-limit response shape, account-scoped cache
expiry, preserving full local history, a 110-tool catalog, complete system
instructions, and historical versus current-turn image behavior.

Live synthetic transport checks showed missing markers in 44,228- and
560,228-character prompts, while all five markers survived 28,228 characters.
A repaired long-context request returned the expected marker via HTTP 200.
These observations motivate a conservative budget; they do not guarantee a
provider-wide fixed limit or that all historical detail is simultaneously visible.

## Original local deployment — 2026-10-16

Windows, upstream 0.16.1 at revision `e34b5082d6c16283358d8a1e3cbd7fa61c35fc0d`, CC Switch 3.19.2, Claude Code 2.1.229 and Claude Desktop 2.31226.1.0.

Observed live results before publication:

- Both configured models returned text through CC Switch, with complete SSE endings.
- A long text request completed after moving conversation data out of the initialization URL.
- Text and PDF fixtures returned their embedded markers; a PNG returned the correct color sequence.
- A short MP4 returned the correct red-to-blue transition.
- Claude Code CLI performed actual Read → Write; the resulting file matched a random marker not supplied in the prompt.
- Claude Desktop Code performed actual Read/Write and image analysis.
- A different MP4 selected through the desktop Add files or photos dialog returned its green-to-yellow transition using the local helper. The prompt did not disclose either color or the local path.

These are observations from one local environment, not a guarantee across all accounts and client versions. Private screenshots, transcripts, paths and account details are intentionally excluded from the public repository.

## Publication changes

The public copy removes machine-specific paths, locates the helper relative to the installation, initializes a per-installation key, protects the private directory, and checks exact installation ownership before stopping a proxy. The original active deployment is kept separate.

`python tests/run.py` runs:

- 16 bridge unit tests with a mocked upstream;
- an offline routing/authentication/long-URL regression script;
- 2 portability tests (initialization/key reuse/UTF-8 and helper path generation).

Tests create their own temporary state and do not require real session cookies. The publication check also installs the dependency lock into a fresh Windows Python 3.12 environment and parses every PowerShell script. GitHub Actions repeats offline tests on Windows. These packaging checks do not constitute a new live desktop acceptance test of every publication change.

`pwsh -File tests/check_process_ownership.ps1` additionally checks that the launcher ownership guard accepts this installation's interpreter or its configured Windows base-interpreter child, always requires the exact launcher, and rejects another interpreter, a filename prefix collision, and a missing process. It does not start or stop any proxy process.

Not fully validated: Cowork, long real-world video/audio, complex multi-step projects, remote cloud file IDs, Linux/macOS integration, native long-context equivalence, provider-internal model identity, or native thinking signatures.

## 1.2.3 recovery-loop guard — 2026-10-16

A live ~980k-char session looped for 20+ minutes: the inline window held only
the model's own snapshot search turns, the original request sat far back, and
the model re-read the snapshot tail without converging (~180 Computer
requests). Three changes:

- context_transport pins `original_user_request` (first real user text, head
  excerpt when bounded) alongside `active_user_request`; snapshot instructions
  now warn that recent messages may be the model's own search turns and direct
  offset jumps instead of tail rescanning.
- anthropic_bridge adds a loop guard: 5+ consecutive trailing tool turns that
  only Read the local context snapshot inject a LOOP GUARD correction into the
  protocol prefix (no request is blocked).
- Regression coverage: original-request pinning, dedup when original equals
  active, guard trigger/quiet/reset cases. Offline suites: 45 tests pass.

## 1.2.4 self-created thread cleanup — 2026-10-16

Every Computer/ASI turn creates one new thread on the Perplexity web app
(visible in the History sidebar as "Local File ..." entries). Long sessions
therefore flood the account history. 1.2.4 removes the thread the proxy itself
created, once the turn is finished:

- New `thread_janitor.py`: best-effort `DELETE /rest/thread` with
  `{"entry_uuids":[backend_uuid], "context_uuids":[], "read_write_token":...}`.
  Endpoint and body shape recovered from the official web frontend's sidebar
  delete action. Only the backend_uuid captured during the current turn is
  ever deleted — no other account data is touched.
- computer_backend captures `read_write_token` from the SSE stream alongside
  `backend_uuid`, and the reconnect loop is wrapped in try/finally so cleanup
  runs on every exit: success, upstream failure, cancellation, timeout.
- Cleanup failure is logged and swallowed; it can never change the request
  outcome. `PWM_THREAD_CLEANUP=0` disables it entirely.
- Scope: Computer/ASI route only. The plain search route (upstream library
  Conversation) has no delete channel and is left unchanged.
- Regression coverage: delete after success, delete failure never breaks the
  answer, delete after upstream failure, env opt-out, no delete when no task
  was created. Offline suites: 50 tests pass.

## 1.2.5 review corrections — 2026-10-16

Three issues found in independent offline review of 1.2.3/1.2.4 are corrected:

- The loop guard now compares the requested snapshot range and returned
  evidence. Forward reads, different snapshot files, and newly returned
  evidence do not count as repeated reads. Equivalent snapshot paths with new
  cache hashes can still trigger the guard when range and evidence repeat.
- Cleanup now uses one daemon worker, a bounded 64-job queue, independent
  per-job sessions and a 10-second delete timeout. The application answer and
  concurrency slot no longer wait for deletion. Overflow is logged and
  skipped. Interpreter exit allows two seconds to drain; forced termination
  or drain timeout may leave self-created threads. No durable queue is written.
- Delete confirmation requires an affirmative JSON result (`status: "success"`,
  `success: true`, or an explicit empty `failed` list), without conflicting error fields.
  Malformed, negative or unrecognized responses never emit a removal-success
  log. Unknown shapes remain unconfirmed pending real endpoint verification.

`python tests/run.py`: 66 unit tests pass (31 bridge, 14 computer, 9 janitor,
5 context, 5 upload, 2 portability), plus routing/authentication smoke checks.
New coverage includes advancing offsets, changed evidence, changed snapshot
hashes, mixed human/reminder blocks, cancellation and timeout after task ID,
token forwarding, explicit success/failure/non-JSON responses, queue overflow,
shutdown rejection, independent session ownership, worker survival after a
session error, and a blocked cleanup that does not block the completed answer.

The local handoff directory is excluded from Git because it can contain
private incident details. This section records offline verification; final
client acceptance and real history-list observations are separate evidence.

Live proxy smoke check on 2026-10-16 at 21:14 (Asia/Shanghai):

- A minimal no-tools Opus request returned HTTP 200 with the exact random
  marker in 3.52 seconds, with ASI / `pplx_asi_opus` confirmed in the stream.
- The actual delete endpoint returned `{"status":"success","failed":null}`;
  this affirmative shape is covered by the response-validation tests.
- The bridge completed at 21:14:08.292; background removal was confirmed at
  21:14:09.202, after the answer had already returned.
- A read-only history search for that exact synthetic marker returned HTTP
  200 and zero entries. Its first attempt encountered a transient TLS error;
  a single read-only retry succeeded. No unrelated history was modified.

This verifies one synthetic real request and its cleanup, not the final
Claude client long-session/video acceptance or a visual browser-history check.

## 1.2.6 Desktop recovery-cycle repair — 2026-10-16

User acceptance of 1.2.5 reproduced the recovery loop despite the earlier short
tool-chain smoke test. The captured Desktop trace had 152 messages, 110 tools,
13,146 system characters and 50 tool calls (34 Read, 16 Bash), mostly repeated
handoff reads, listings and changing snapshot-range lookups.

Two deterministic regressions failed before the repair: Desktop appends a
`<total_tokens>` system message after each tool result, which reset the guard;
and optional schemas / recent recovery chatter displaced previously acquired
handoff content. A third test reproduced alternating unchanged-file notices
and advancing snapshot ranges, which the exact-range guard alone missed.

Changes:

- Preserve complete client system instructions and the exact full payload.
  Prefer the latest actual result before optional schemas or old search turns.
  Compact duplicated bridge guidance, not client instructions. Oversized-result
  guidance no longer sends the model back into the snapshot tail by default.
- Store actual client results under stable content-addressed evidence paths.
  Pin bounded exact excerpts with explicit excerpt flags and full-result paths;
  exclude snapshot/evidence lookup wrappers and unchanged-file notices from
  the source-evidence cache. No model-generated progress summary is used.
- Ignore Desktop token metadata for loop counting. Detect the observed mixed
  pattern of repeated unchanged notices plus snapshot lookups and direct
  recovery to the actual result evidence. Advancing ranges without the mixed
  stale-read pattern still do not trigger the exact-range guard.

Offline verification: 72 unit tests pass (33 bridge, 14 computer, 9 janitor,
9 context, 5 upload, 2 portability) plus routing/auth smoke checks. Tests cover
the three previously failing cases, exact stable-result persistence without
rewriting unchanged files, Windows shell snapshot paths, and full latest-result
priority while retaining complete system instructions.

Live recovery probes used the real ASI/Opus backend:

- Replayed the captured 152-message trace. Two sequential reads of a stable
  directory-result file led to a new targeted inspection of previously
  unexamined review/baseline folders, without another context-tail scan. That
  requested project inspection was observed, not executed by the proxy probe.
- A controlled implementation task reused the Desktop-sized system/tool
  catalog and included 20 old recovery turns with token metadata. The next
  response requested Write with the correct marker from the earlier handoff;
  the restricted test client wrote only its temporary fixture output and
  verified the exact bytes. No production project files were changed.
- Repeated that controlled long recovery task through the restarted local
  1.2.6 HTTP proxy. Its first new response again requested the correct Write;
  the fixture output was independently read back and matched the marker.

These probes cover recovery behavior missed by the short smoke test. Final
acceptance of the user's actual Desktop project and long video task remains
separate; model behavior is not guaranteed for every future conversation.
