"""Live bad/good gate for Rust templates.

`test_template_accuracy` only checks templates that have both recorded
expected-line metadata and a prebuilt `ast.json` fixture pair, which excludes
most Rust rules. This drives each Rust template against its `bad/` and `good/`
mocks through the real parser so a rule that stops detecting its bug, fires on
the safe variant, or throws is caught in CI.

The variant is parsed as one unit rather than file by file, matching a real
scan: a rule whose first pass collects from `state/` and whose second judges
`instructions/` is otherwise unable to fire here even though it works in
production, and its mock proves nothing.

It parses Rust live (via `rust_syn`), so it is marked `active_runtime` and runs
under `make test-all` / the Docker image, not the fixture-only `make test`.
"""

import pytest

from tests.check_scoping import rust_stems_with_fixtures, scan_variants

STEMS = rust_stems_with_fixtures()

# Every Rust template with bad/good fixtures is expected to detect its bad mock
# and stay clean on good. Keep this set as small as it can be: an entry here is
# coverage the scanner does not have, and the reason has to be structural
# rather than "the rule needs work".
KNOWN_BROKEN = {
    # Keys on Rust doc comments, which reach syn as a synthesized `doc`
    # attribute with no counterpart in the source text, so span resolution
    # drops the node before the DSL sees it. Same reason `test_templates`
    # lists it in ARCHITECTURALLY_UNDETECTABLE; needs real parser spans.
    "missing_security_documentation",
}


@pytest.mark.active_runtime
@pytest.mark.parametrize("stem", STEMS, ids=STEMS)
def test_anchor_template_scoping(stem, request):
    if stem in KNOWN_BROKEN:
        request.node.add_marker(
            pytest.mark.xfail(reason="pre-existing: rule misses its own bad fixture", strict=False)
        )
    counts = scan_variants(stem)
    assert counts is not None, f"No Rust bad/good fixtures for {stem}"

    bad_errors = [h for h in counts["bad"] if str(h).startswith("ERROR")]
    good_errors = [h for h in counts["good"] if str(h).startswith("ERROR")]
    assert not bad_errors, f"{stem}: rule threw on bad fixture: {bad_errors}"
    assert not good_errors, f"{stem}: rule threw on good fixture: {good_errors}"

    bad_hits = [h for h in counts["bad"] if not str(h).startswith("ERROR")]
    assert bad_hits, f"{stem}: MISSED the bug — no detection on bad fixture"
    assert counts["good"] == [], f"{stem}: FALSE POSITIVE on good fixture: {counts['good']}"


def test_scoping_gate_covers_templates():
    """Guard against the gate silently covering nothing (empty parametrization)."""
    assert STEMS, "No Rust templates with bad/good fixtures were discovered"
