"""Validate a template against its bad/good mocks, plus a scoping fixture.

The accuracy suite skips any template without recorded expected-line metadata,
which is most of them. This drives the same machinery directly so a rule can be
checked while it is being rewritten:

    .venv/bin/python tests/check_scoping.py [template_stem ...]

For each template it reports detections on mocks/<name>/bad (expected: at least
one) and mocks/<name>/good (expected: none). With no arguments it checks every
template that has both fixtures.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_templates import run_template_on_rust_sources  # noqa: E402

# Prefer the repo-relative templates dir so this runs from a dev checkout; fall
# back to the container path (`/api/builtin_templates`) when run inside the
# Docker image where the repo root is `/api`.
_REPO_TEMPLATES = Path(__file__).resolve().parent.parent / "builtin_templates"
TEMPLATES = _REPO_TEMPLATES if _REPO_TEMPLATES.is_dir() else Path("/api/builtin_templates")
MOCKS = Path(__file__).resolve().parent / "mocks"


def sources(directory: Path):
    return sorted(p for p in directory.rglob("*.rs"))


def rust_stems_with_fixtures():
    """Every Rust template stem that has bad/ and good/ Rust mock sources.

    This used to select on `accent == "anchor"`, from when accent was a proxy
    for "is this a Solana rule". The accent silo made it a floor instead - a
    rule accented `rust` or `solana` runs on Anchor sources too - so that filter
    now excludes most of the rules it was meant to cover. Select on the language
    the harness can actually drive, and let the mock's presence decide the rest.

    Shared with the pytest gate so the script and CI check the same set.
    """
    stems = []
    for template_path in sorted(TEMPLATES.glob("*.yaml")):
        stem = template_path.stem
        try:
            data = yaml.safe_load(template_path.read_text())
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("language", "rust") != "rust":
            continue
        mock = MOCKS / stem
        if not (mock / "bad").is_dir() or not (mock / "good").is_dir():
            continue
        if not sources(mock / "bad"):
            continue  # Solidity fixtures; this harness only drives the Rust path
        stems.append(stem)
    return stems


def scan_variants(stem: str):
    """Run template `stem` against its bad/good mocks; return {variant: [hits]}.

    A hit is a detection location, or an ``ERROR ...`` string if the rule threw.
    Returns None if the template or its Rust fixtures are absent.
    """
    template_path = TEMPLATES / f"{stem}.yaml"
    if not template_path.exists():
        return None
    data = yaml.safe_load(template_path.read_text())
    if data.get("language", "rust") != "rust":
        return None
    mock = MOCKS / stem
    if not (mock / "bad").is_dir() or not (mock / "good").is_dir():
        return None
    if not sources(mock / "bad"):
        return None

    counts = {}
    for variant in ("bad", "good"):
        variant_sources = sources(mock / variant)
        try:
            # One AST for the whole variant, matching a real scan. Parsing each
            # file separately would hide any rule whose two passes span files.
            result = run_template_on_rust_sources(data, variant_sources)
        except Exception as exc:  # a rule that throws is a rule that is broken
            counts[variant] = [f"ERROR {mock.name}/{variant}: {exc}"]
            continue
        counts[variant] = list(result.get("locations", []))
    return counts


def check(stem: str):
    counts = scan_variants(stem)
    if counts is None:
        return None
    data = yaml.safe_load((TEMPLATES / f"{stem}.yaml").read_text())

    detects = len(counts["bad"]) > 0
    clean = len(counts["good"]) == 0
    verdict = "PASS" if detects and clean else "FAIL"
    print(f"{verdict}  {data['name']}")
    print(f"        bad : {len(counts['bad'])} detection(s)" + ("" if detects else "   <-- MISSES THE BUG"))
    print(f"        good: {len(counts['good'])} detection(s)" + ("" if clean else "   <-- FALSE POSITIVE"))
    for location in counts["good"]:
        print(f"              {location}")
    return verdict == "PASS"


def main():
    stems = sys.argv[1:]
    if not stems:
        stems = sorted(p.stem for p in TEMPLATES.glob("*.yaml") if (MOCKS / p.stem).is_dir())

    results = [(stem, check(stem)) for stem in stems]
    checked = [(s, r) for s, r in results if r is not None]
    failed = [s for s, r in checked if r is False]
    print(f"\n{len(checked) - len(failed)}/{len(checked)} passed")
    if failed:
        print("failing: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
