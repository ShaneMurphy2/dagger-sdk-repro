#!/usr/bin/env python3
"""Compare warm SDK checks before, during, and after an ignored file tree."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent
COMMAND = ["mise", "exec", "--", "dagger", "check", "--progress=plain", "-vvv"]


def inputs_digest():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths) - {b""}):
        digest.update(name + b"\0" + (ROOT / os.fsdecode(name)).read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=50_000)
    parser.add_argument("--bytes", type=int, default=256)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    if min(args.files, args.bytes, args.runs) < 1:
        parser.error("--files, --bytes, and --runs must be positive")

    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    if any(build.iterdir()):
        parser.error(".build must be empty before starting the comparison")
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    before = inputs_digest()
    samples = []

    def measure(phase):
        # Discard the first run after each filesystem change to warm the cache.
        for index in range(args.runs + 1):
            log = results / f"{phase}-{index}.log"
            start = time.perf_counter()
            with log.open("w") as output:
                result = subprocess.run(COMMAND, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
            elapsed = time.perf_counter() - start
            # GitHub Actions adds ANSI colors even with --progress=plain.
            text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log.read_text())
            text = text.replace(str(ROOT), "<workspace>")
            log.write_text(text)
            if result.returncode:
                raise SystemExit(f"Dagger check failed; see {log}")
            sdk = re.search(r"dag://\?check=typescript-sdk/generate/stale DONE \[([\d.]+)s\]", text)
            if not sdk:
                raise SystemExit(f"SDK freshness timing missing; see {log}")
            reads = re.findall(r"Host\.directory DONE \[([\d.]+)s\]", text)
            row = dict(phase=phase, run=index, warmup=index == 0,
                       wall_seconds=round(elapsed, 3), sdk_seconds=float(sdk[1]),
                       longest_host_read_seconds=max(map(float, reads), default=0))
            samples.append(row)
            print(json.dumps(row), flush=True)

    measure("empty")
    # TemporaryDirectory removes only the synthetic files this run created.
    with tempfile.TemporaryDirectory(prefix="synthetic-", dir=build) as directory:
        fixture = Path(directory)
        payload = b"x" * args.bytes
        print(f"Creating {args.files:,} ignored files ({args.files * args.bytes:,} bytes).", flush=True)
        for index in range(args.files):
            parent = fixture / f"package-{index // 100:05d}"
            if index % 100 == 0:
                parent.mkdir()
            (parent / f"artifact-{index:06d}.o").write_bytes(payload)
        subprocess.run(["git", "check-ignore", "-q", str(fixture / "package-00000/artifact-000000.o")],
                       cwd=ROOT, check=True)
        measure("ignored")
    measure("restored")

    unchanged = before == inputs_digest()
    summary = dict(files=args.files, bytes_per_file=args.bytes, command=COMMAND,
                   inputs_unchanged=unchanged, samples=samples)
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not unchanged:
        raise SystemExit("Source/config changed during the comparison; see results/summary.json")
    print("All checks passed; source/config unchanged. See results/summary.json.")


if __name__ == "__main__":
    main()
