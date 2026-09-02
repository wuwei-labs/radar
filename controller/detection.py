"""What the scanned source is, read from its manifests.

Deliberately free of any Django or network coupling: the answer decides which
templates run, and that decision should be testable without standing up the
service.
"""

from pathlib import Path


# Protocols a program integrates with, keyed on the crate it depends on to do
# so. Read from the same manifests the framework comes from, so a scan runs a
# protocol's rules only against sources that actually pull it in.
PROTOCOL_CRATES = {
    "antegen": ("antegen-thread-program", "antegen-fiber-program", "antegen-cron"),
    "metaplex": ("mpl-token-metadata", "mpl-bubblegum", "mpl-candy-machine"),
    "squads": ("squads-multisig", "squads-multisig-program"),
}


def detect_protocols_from_manifests(cargo_files) -> list:
    """Protocols named by any manifest under the scanned path."""
    found = set()
    for cargo_file in cargo_files:
        try:
            content = cargo_file.read_text()
        except Exception:
            continue
        for protocol, crates in PROTOCOL_CRATES.items():
            if any(crate in content for crate in crates):
                found.add(protocol)
    return sorted(found)


def detect_language_from_path(path: Path) -> tuple[str, str, list]:
    """Detect language, framework and protocols from a file or folder.
    
    Returns: (language, framework, protocols) tuple
    """
    if path.is_file():
        if path.suffix == ".sol":
            return ("solidity", "standalone", [])
        elif path.suffix == ".rs":
            return ("rust", "unknown", [])
    elif path.is_dir():
        # Check for .sol files
        try:
            next(path.glob("**/*.sol"))
            # Check if it's a Foundry project
            if (path / "foundry.toml").exists():
                return ("solidity", "foundry", [])
            else:
                return ("solidity", "standalone", [])
        except StopIteration:
            pass

        # Check for Rust project (Cargo.toml, recursive)
        try:
            cargo_files = list(path.glob("**/Cargo.toml"))
            if not cargo_files:
                raise StopIteration

            protocols = detect_protocols_from_manifests(cargo_files)

            # Detect Rust framework - check Cargo.toml dependencies first.
            # Anchor and Stylus are asked about before plain Solana: an Anchor
            # program depends on solana-program too, and the more specific
            # answer is the one that selects the right templates.
            framework_detected = None
            solana_seen = False
            for cargo_file in cargo_files:
                try:
                    content = cargo_file.read_text()
                except Exception:
                    continue
                if "anchor-lang" in content or "anchor-spl" in content:
                    framework_detected = "anchor"
                    break
                if "stylus-sdk" in content:
                    framework_detected = "stylus"
                    break
                if (
                    "solana-program" in content
                    or "solana-sdk" in content
                    or "pinocchio" in content
                ):
                    # Keep looking: a sibling manifest may still name Anchor.
                    solana_seen = True

            if framework_detected is None and solana_seen:
                framework_detected = "solana"

            # If detected from dependencies, return that
            if framework_detected:
                return ("rust", framework_detected, protocols)

            # Otherwise check for config files
            if (path / "Anchor.toml").exists():
                return ("rust", "anchor", protocols)
            elif (path / "Xargo.toml").exists():
                return ("rust", "stylus", protocols)
            else:
                return ("rust", "unknown", protocols)
        except StopIteration:
            pass
    return ("unknown", "unknown", [])
