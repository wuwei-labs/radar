"""Which templates a scan runs, given what the source turned out to be.

Two independent questions, and keeping them apart is the point:

  accent   what the rule needs to exist at all - plain Rust, Solana, Anchor,
           Stylus. A framework inherits everything more general than itself, so
           an Anchor scan runs `anchor` + `solana` + `rust`. Most rules that
           carry Solana logic were tagged `anchor` only by habit; treating the
           accent as a floor rather than an exact match is what lets them reach
           a native program.

  protocol what the program integrates with - squads, metaplex, antegen. Read
           from the same manifests as the framework, so no flag is needed for
           the ordinary case. A rule without a protocol applies to everyone in
           its accent.

`unknown` deliberately runs everything: it is the honest answer when no
manifest claimed anything, and the sources we know least about are the last
ones that should get fewer checks.
"""

# What a framework may run: itself, plus everything more general.
ACCENTS_FOR_FRAMEWORK = {
    "anchor": {"anchor", "solana", "rust"},
    "solana": {"solana", "rust"},
    "stylus": {"stylus", "rust"},
}


def accents_for(framework: str) -> set:
    """Accents a scan of `framework` is allowed to run."""
    return ACCENTS_FOR_FRAMEWORK.get(framework, {framework})


def template_applies(
    template: dict,
    detected_language: str,
    detected_framework: str,
    detected_protocols=(),
) -> bool:
    """Whether this template runs against a source described this way."""
    if template.get("language", "rust") != detected_language:
        return False

    accent = template.get("accent", "")
    if detected_language == "rust" and accent and detected_framework != "unknown":
        if accent not in accents_for(detected_framework):
            return False

    protocol = template.get("protocol", "")
    if protocol and protocol not in set(detected_protocols or ()):
        return False

    return True
