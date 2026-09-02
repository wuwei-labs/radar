"""Framework and protocol detection from a source tree's manifests.

Both answers come from the same Cargo.toml read. The framework picks which
accents a scan runs; the protocols pick which protocol packs it runs. Neither
needs a flag for the ordinary case, which is the point - a flag nobody sets is
a pack nobody runs.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detection import detect_language_from_path, detect_protocols_from_manifests


def write_crate(root: Path, name: str, deps: str) -> Path:
    crate = root / name
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        f'[package]\nname = "{name}"\nversion = "0.1.0"\n\n[dependencies]\n{deps}\n'
    )
    (crate / "src" / "lib.rs").write_text("// test\n")
    return crate


class TestFrameworkDetection:
    def test_anchor(self, tmp_path):
        write_crate(tmp_path, "prog", 'anchor-lang = "0.30"')
        assert detect_language_from_path(tmp_path)[:2] == ("rust", "anchor")

    def test_native_solana(self, tmp_path):
        write_crate(tmp_path, "prog", 'solana-program = "1.18"')
        assert detect_language_from_path(tmp_path)[:2] == ("rust", "solana")

    def test_pinocchio_is_native_solana(self, tmp_path):
        write_crate(tmp_path, "prog", 'pinocchio = "0.6"')
        assert detect_language_from_path(tmp_path)[:2] == ("rust", "solana")

    def test_stylus(self, tmp_path):
        write_crate(tmp_path, "prog", 'stylus-sdk = "0.6"')
        assert detect_language_from_path(tmp_path)[:2] == ("rust", "stylus")

    def test_anchor_wins_over_solana(self, tmp_path):
        # An Anchor program depends on solana-program too. Reporting `solana`
        # would drop the anchor-accent rules, which are the ones that read its
        # accounts structs.
        write_crate(tmp_path, "prog", 'anchor-lang = "0.30"\nsolana-program = "1.18"')
        assert detect_language_from_path(tmp_path)[1] == "anchor"

    def test_anchor_in_a_sibling_manifest_still_wins(self, tmp_path):
        # A workspace whose first crate is a plain Solana helper must not be
        # reported as native just because that manifest was read first.
        write_crate(tmp_path, "aaa_helper", 'solana-program = "1.18"')
        write_crate(tmp_path, "zzz_program", 'anchor-lang = "0.30"')
        assert detect_language_from_path(tmp_path)[1] == "anchor"

    def test_rust_without_a_recognised_framework_is_unknown(self, tmp_path):
        write_crate(tmp_path, "prog", 'serde = "1"')
        assert detect_language_from_path(tmp_path)[:2] == ("rust", "unknown")


class TestProtocolDetection:
    @pytest.mark.parametrize(
        "dep,expected",
        [
            ("antegen-thread-program = \"5.2\"", ["antegen"]),
            ("mpl-token-metadata = \"4\"", ["metaplex"]),
            ("squads-multisig = \"2\"", ["squads"]),
            ("serde = \"1\"", []),
        ],
    )
    def test_single_protocol(self, tmp_path, dep, expected):
        write_crate(tmp_path, "prog", f'anchor-lang = "0.30"\n{dep}')
        assert detect_language_from_path(tmp_path)[2] == expected

    def test_multiple_protocols_across_manifests(self, tmp_path):
        write_crate(tmp_path, "one", 'anchor-lang = "0.30"\nantegen-cron = "4"')
        write_crate(tmp_path, "two", 'anchor-lang = "0.30"\nmpl-bubblegum = "1"')
        assert detect_language_from_path(tmp_path)[2] == ["antegen", "metaplex"]

    def test_unreadable_manifest_is_skipped_not_fatal(self, tmp_path):
        write_crate(tmp_path, "prog", 'antegen-cron = "4"')
        missing = tmp_path / "gone" / "Cargo.toml"
        assert detect_protocols_from_manifests(
            [missing, tmp_path / "prog" / "Cargo.toml"]
        ) == ["antegen"]

    def test_non_rust_paths_report_no_protocols(self, tmp_path):
        (tmp_path / "a.sol").write_text("contract A {}\n")
        assert detect_language_from_path(tmp_path)[2] == []
