# Slow SDK freshness checks with ignored build files

A minimal Dagger 1.0 beta workspace with one TypeScript module whose only
function returns `"hello"`. `dagger check` runs the SDK's generated-file
freshness check; there are no user-defined checks or build tools.

Pinned versions:

- Dagger candidate `01ef75dd5f763e941d009330defb79193db9c82e` (beta.22).
- TypeScript SDK v1.0.4, with dependencies pinned in `dagger.lock`.
- The mise tool entry installs beta.21 as a bootstrap; `DAGGER_X_RELEASE`
  selects the candidate CLI and engine.

## Observed result

On macOS ARM64, 2026-10-28, using the pinned candidate:

| Workspace state | Warm SDK freshness checks | Longest host directory read |
| --- | --- | --- |
| Empty `.build/` | 1.2s / 1.2s | <0.1s |
| 50,000 ignored files | 7.7s / 7.5s | 6.0s / 5.8s |
| Synthetic files removed | 1.2s / 1.2s | <0.1s |

All nine checks, including warm-ups, passed. Source/config hashes remained
unchanged throughout the comparison. See [observed-results.json](observed-results.json)
for every sample and [trace-excerpt.txt](trace-excerpt.txt) for the slow call.

The slow read is `Host.directory` with `gitignore: true` and no explicit
include/exclude filter, inside `WorkspaceSDK.generate`. The module itself
does not read any workspace files. This isolates a cost associated with the
ignored tree; the trace does not distinguish traversal, hashing, and transfer.
Exact timings depend on the machine and filesystem.

## Run

Requires Git, Python 3, mise, and a running Docker engine.

```sh
# After cloning this repository:
mise trust
mise install
python3 repro.py
```

The script runs the same command before, during, and after adding 50,000
synthetic files beneath the gitignored `.build/` directory:

```sh
mise exec -- dagger check --progress=plain -vvv
```

Each phase discards one warm-up run, then measures two unchanged runs. The
script verifies Git ignores the fixture and that source/config files remain
unchanged. It removes its synthetic files after the populated phase and saves
logs and timings under the ignored `results/` directory. `.build/` must be
empty before starting. The fixture has 12.8 MB of file contents; actual disk
usage is larger because there are many small files.

For a larger comparison:

```sh
python3 repro.py --files 100000 --runs 3
```

Inspect `results/summary.json` and search the populated-phase logs for
`WorkspaceSDK.generate`, `Host.directory`, and `gitignore: true`.
SDK/read timings come from Dagger's rounded progress output; wall time uses
Python's monotonic timer. Trace parent and child durations overlap, so do not
add every `Host.directory` and `uploading` span together.

Generated SDK files are included so a clone can immediately run the freshness
check. To regenerate after an intentional module or engine change:

```sh
mise exec -- dagger generate -y
```

## GitHub Actions

The included `.github/workflows/repro.yml` runs on pushes, pull requests, and
manual dispatch. Push this repository with the generated `.dagger/` files and
`dagger.lock`; no Dagger Cloud account or repository secrets are needed.

The job uses GitHub's `ubuntu-24.04` runner and its Docker daemon, installs the
pinned Dagger version through mise, and runs `python3 repro.py`. All nine
checks run in one job against one engine, with a warm-up per phase. No cache
is restored from earlier workflow runs. A passing job means the checks
succeeded and source/config stayed unchanged; it does not assert a particular
slowdown on every runner.

Open **Actions → SDK freshness repro → a run** for a table of the measured
timings. The `sdk-freshness-results` artifact contains `results/summary.json`,
the full progress logs, and `results/environment.txt`, retained for 30 days.
Logs are uploaded even if a check fails. Share the workflow run URL with
maintainers. Linux timings may differ from the macOS results above.
