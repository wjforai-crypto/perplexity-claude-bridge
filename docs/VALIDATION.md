# Validation scope

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
