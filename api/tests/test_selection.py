"""Which templates a scan selects, per accent and protocol.

The accent rules exist because tagging was never precise: most templates
carrying Solana logic were marked `anchor` regardless of whether they needed
Anchor syntax. Treating an accent as a floor rather than an exact match is what
lets those reach a native program - and that is not hypothetical, it is how
`unvalidated_sysvar_accounts` reaches Wormhole, which uses solitaire rather than
Anchor.
"""

import pytest

from utils.selection import accents_for, template_applies


def rule(**kwargs):
    base = {"language": "rust", "accent": "solana"}
    base.update(kwargs)
    return base


class TestAccentInheritance:
    def test_anchor_runs_anchor_solana_and_rust(self):
        assert accents_for("anchor") == {"anchor", "solana", "rust"}

    def test_native_solana_does_not_run_anchor_rules(self):
        assert "anchor" not in accents_for("solana")
        assert accents_for("solana") == {"solana", "rust"}

    def test_stylus_is_not_given_solana_rules(self):
        # Stylus is Arbitrum. Solana rules are meaningless there, and it ships
        # its own arithmetic checks, so only the chain-agnostic ones are shared.
        assert accents_for("stylus") == {"stylus", "rust"}

    def test_unknown_framework_runs_everything(self):
        # No manifest claimed anything. Narrowing here would silence rules on
        # exactly the sources we know least about.
        for accent in ("rust", "solana", "anchor", "stylus"):
            assert template_applies(rule(accent=accent), "rust", "unknown")


class TestAccentSelection:
    @pytest.mark.parametrize(
        "framework,accent,expected",
        [
            ("anchor", "anchor", True),
            ("anchor", "solana", True),
            ("anchor", "rust", True),
            ("anchor", "stylus", False),
            ("solana", "solana", True),
            ("solana", "rust", True),
            ("solana", "anchor", False),
            ("stylus", "stylus", True),
            ("stylus", "rust", True),
            ("stylus", "solana", False),
        ],
    )
    def test_matrix(self, framework, accent, expected):
        assert template_applies(rule(accent=accent), "rust", framework) is expected

    def test_language_still_gates_first(self):
        solidity = {"language": "solidity", "accent": ""}
        assert not template_applies(solidity, "rust", "anchor")


class TestProtocolSelection:
    def test_protocol_rule_runs_only_for_a_dependent_source(self):
        antegen = rule(protocol="antegen")
        assert template_applies(antegen, "rust", "anchor", ["antegen"])
        assert not template_applies(antegen, "rust", "anchor", [])
        assert not template_applies(antegen, "rust", "anchor", ["squads"])

    def test_rule_without_protocol_applies_to_everyone(self):
        assert template_applies(rule(), "rust", "anchor", [])

    def test_protocol_does_not_override_accent(self):
        # A Solana protocol pack has no business running on a Stylus source
        # just because the protocol was somehow reported.
        pack = rule(accent="solana", protocol="antegen")
        assert not template_applies(pack, "rust", "stylus", ["antegen"])
