"""Score the rules against ScannerTruth's corpus-2 pack, and fail on a regression.

The fixture gates in `pytest.yml` are ours: we wrote the vulnerable files, so
they measure what we thought to check. This measures the rules against
seventeen real-world Solana bugs someone else chose, packaged with their own
mapping and their own scorer, and it is the only number here that is
out-of-sample.

Not a merge gate. The mapping is upstream's, over public crates, and a `missed`
there is a coverage limit rather than a defect - most of the misses are classes
radar has no rule for at all. What *is* a defect is going backwards, so this
compares against `corpus2_baseline.json` and fails only when a case scores worse
than it did.

    python tests/corpus2_regression.py                  # score, compare, exit 1 on regression
    python tests/corpus2_regression.py --write-baseline # re-record after an intended change
    SCANNERTRUTH_DIR=/path/to/checkout python tests/corpus2_regression.py

Scanning is done in-process rather than through the radar CLI: the pack's
`run.sh` drives Docker, which CI does not have, and a container per variant is
34 cold starts to compute something the DSL can answer directly. The output is
written in the exact shape `check.py` reads, and the scoring is then upstream's
code, unmodified.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = API_ROOT.parent
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from utils.ast import generate_ast_for_rust_file  # noqa: E402
from utils.dsl.dsl import (  # noqa: E402
    inject_code_lines,
    process_template_outputs,
    wrapped_exec,
)
from utils.selection import template_applies  # noqa: E402
from controller.detection import detect_language_from_path  # noqa: E402

# Pinned by full commit SHA: the scorer and the mapping are the measurement, so
# they cannot be allowed to drift underneath a baseline recorded against them.
SCANNERTRUTH_REPO = "https://github.com/halobartku/scannertruth.git"
SCANNERTRUTH_SHA = "26f5e5a6fdf8d380a646db3b786d61bba9b1cb32"

BASELINE = Path(__file__).resolve().parent / "corpus2_baseline.json"
TEMPLATES = API_ROOT / "builtin_templates"

# Better to worse. `no-rule` sits level with `missed` deliberately: it means the
# mapping names no rule for the class, so no change to our rules can move it,
# and treating it as a distinct rank would make an upstream mapping edit look
# like our regression.
VERDICT_RANK = {"detected": 3, "unlocated": 2, "missed": 1, "no-rule": 1, "not-run": 0}


def fetch_pack() -> Path:
    """The pack, from a local checkout if given, else cloned at the pinned SHA."""
    local = os.environ.get("SCANNERTRUTH_DIR")
    if local:
        pack = Path(local) / "regression-pack-radar"
        if not pack.is_dir():
            sys.exit(f"[e] No regression-pack-radar under SCANNERTRUTH_DIR={local}")
        print(f"[i] Using local pack at {pack}")
        return pack

    checkout = Path(tempfile.mkdtemp(prefix="scannertruth-")) / "scannertruth"
    print(f"[i] Cloning {SCANNERTRUTH_REPO} at {SCANNERTRUTH_SHA[:12]}")
    subprocess.run(
        ["git", "clone", "--quiet", SCANNERTRUTH_REPO, str(checkout)], check=True
    )
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", "--quiet", SCANNERTRUTH_SHA], check=True
    )
    return checkout / "regression-pack-radar"


def rules_for(variant_dir: Path):
    """The templates a real scan of this variant would run.

    Selection is not cosmetic here. The pack's synthetic manifests declare
    `solana-program`, so every case detects as native Solana and the seven
    Anchor-accented rules do not apply. Running them anyway would score rules
    against sources radar would never point them at.
    """
    language, framework, protocols = detect_language_from_path(variant_dir)
    selected = []
    for path in sorted(TEMPLATES.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or data.get("language", "rust") != "rust":
            continue
        if not template_applies(data, language, framework, protocols):
            continue
        selected.append(data)
    return selected


def scan(variant_dir: Path):
    """Findings for one variant, in the shape check.py reads."""
    sources = sorted(variant_dir.rglob("*.rs"))
    if not sources:
        return [], 0

    items = []
    for source in sources:
        items.extend(generate_ast_for_rust_file(source)["ast"])

    findings = []
    for data in rules_for(variant_dir):
        code = inject_code_lines(
            data["rule"], [f"ast = parse_ast({items}, language='rust').items()"]
        )
        try:
            result = process_template_outputs(wrapped_exec(code), data)
        except Exception as exc:
            # A rule that raises is a defect, not a quiet zero - the whole point
            # of narrowing the sandbox's exception handling. Surface it here too
            # rather than scoring it as "found nothing".
            print(f"[e] {data['name']} raised on {variant_dir}: {type(exc).__name__}: {exc}")
            continue
        locations = result.get("locations") or []
        if locations:
            findings.append({"name": data["name"], "locations": locations})
    return findings, len(sources)


def write_results(pack: Path, results_dir: Path):
    cases = json.loads((pack / "manifest.json").read_text())["cases"]
    for case in cases:
        name = case["name"]
        for variant in ("insecure", "secure"):
            variant_dir = pack / "cases" / name / variant
            if not variant_dir.is_dir():
                continue
            findings, scanned = scan(variant_dir)
            leaf = results_dir / f"{name}.{variant}"
            leaf.mkdir(parents=True, exist_ok=True)
            (leaf / "radar.json").write_text(json.dumps(findings))
            # check.py treats a missing radar.json as a real zero only when the
            # log says a scan happened, so this line is evidence, not decoration.
            (leaf / "stdout.log").write_text(f"[i] Scanned {scanned} files\n")
        print(f"[i] scored {name}")


def score(pack: Path, results_dir: Path) -> dict:
    out = results_dir / "verdicts.json"
    subprocess.run(
        [sys.executable, "check.py", "--results", str(results_dir), "--json", str(out)],
        cwd=str(pack),
        check=True,
    )
    return json.loads(out.read_text())


def compare(current: dict, baseline: dict) -> int:
    rows = {row["id"]: row for row in current["cases"]}
    recorded = baseline.get("cases", {})

    regressions = []
    print(f"\n{'case':38} {'verdict':11} {'was':11} {'on-fixed':>8} {'was':>5}")
    for case_id in sorted(rows):
        row = rows[case_id]
        was = recorded.get(case_id)
        verdict, noise = row["verdict"], row.get("fires_on_fixed") or 0
        if was is None:
            print(f"{case_id:38} {verdict:11} {'(new)':11} {noise:>8} {'-':>5}")
            continue
        old_verdict, old_noise = was["verdict"], was.get("fires_on_fixed") or 0
        print(f"{case_id:38} {verdict:11} {old_verdict:11} {noise:>8} {old_noise:>5}")

        if VERDICT_RANK.get(verdict, 0) < VERDICT_RANK.get(old_verdict, 0):
            regressions.append(f"{case_id}: {old_verdict} -> {verdict}")
        if noise > old_noise:
            regressions.append(
                f"{case_id}: findings on fixed code {old_noise} -> {noise}"
            )

    for case_id in sorted(set(recorded) - set(rows)):
        regressions.append(f"{case_id}: present in the baseline, absent from this run")

    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(current["tally"].items())))
    total = sum(r.get("fires_on_fixed") or 0 for r in current["cases"])
    print(f"findings on fixed variants (upper bound on noise): {total}")

    if regressions:
        print("\n[e] corpus-2 regression:")
        for line in regressions:
            print(f"      {line}")
        print(
            "\n    If the change was intended, re-record with --write-baseline "
            "and say why in the commit."
        )
        return 1
    print("\n[i] No case scored worse than the baseline.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    pack = fetch_pack()
    results_dir = Path(tempfile.mkdtemp(prefix="corpus2-results-"))
    write_results(pack, results_dir)
    current = score(pack, results_dir)

    if args.write_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "scannertruth_sha": SCANNERTRUTH_SHA,
                    "tally": current["tally"],
                    "cases": {
                        row["id"]: {
                            "verdict": row["verdict"],
                            "fires_on_fixed": row.get("fires_on_fixed") or 0,
                        }
                        for row in current["cases"]
                    },
                },
                indent=1,
            )
            + "\n"
        )
        print(f"[i] Baseline written to {BASELINE}")
        return 0

    if not BASELINE.exists():
        sys.exit(f"[e] No baseline at {BASELINE}; record one with --write-baseline")
    return compare(current, json.loads(BASELINE.read_text()))


if __name__ == "__main__":
    raise SystemExit(main())
