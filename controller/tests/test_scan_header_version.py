"""The scan header's build line, exercised against a stubbed docker.

`print_version` in the `radar` wrapper reads two OCI labels off the API image and
prints which build is about to run, warning when that image has gone stale. It
exists because a cached image keeps working silently long after main has moved,
and a scan from a three-day-old image is otherwise indistinguishable from a
current one.

The function is bash, so it is extracted from the wrapper and run with a fake
`docker` on PATH that returns whatever labels the test wants. No daemon, no
images, no network - which is why this can live in the controller job.
"""

import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RADAR = Path(__file__).resolve().parent.parent.parent / "radar"


def _label_date(days_ago: float) -> str:
    """A `created` label that stays that many days old as the clock moves.

    The fresh case cannot use a literal. Written as one it passes on the day it
    is committed and fails once the date drifts past STALE_IMAGE_DAYS - which
    it did, turning a green suite red a week later with nothing changed.
    """
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _extract(name: str) -> str:
    """Pull one function out of the wrapper, plus the settings it reads."""
    source = RADAR.read_text()
    start = source.index(f"{name}() {{")
    depth, i = 0, start
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    threshold = re.search(r"^STALE_IMAGE_DAYS=(\d+)", source, re.M)
    return f"STALE_IMAGE_DAYS={threshold.group(1)}\n" + source[start:i + 1]


def _run(tmp_path, revision, created):
    """Run print_version with a docker stub returning these label values."""
    stub = tmp_path / "docker"
    # `docker inspect --format='{{index .Config.Labels "...revision"}}'` - the
    # stub answers by which label the format string names.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *revision*) echo "{revision}" ;;\n'
        f'  *created*)  echo "{created}" ;;\n'
        "  *) echo '' ;;\n"
        "esac\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    script = tmp_path / "run.sh"
    script.write_text(_extract("print_version") + "\nprint_version\n")

    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="bash wrapper")
def test_current_build_prints_one_line_and_no_warning(tmp_path):
    out = _run(tmp_path, "475c06ecf1370213a8f525f18cffe40425fb1e41", _label_date(1))
    # The commit is what makes a pasted bug report actionable.
    assert "475c06e" in out
    assert "[w]" not in out


def test_a_stale_image_says_so(tmp_path):
    # Two years old: comfortably past any threshold, so this does not become a
    # test that quietly stops asserting as the clock moves.
    out = _run(tmp_path, "2f3b9edaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "2024-01-01T00:00:00.000Z")
    assert "[w]" in out
    assert "radar --update" in out


def test_an_unlabelled_image_says_nothing(tmp_path):
    """A locally built image carries no labels; guessing would be worse than silence."""
    assert _run(tmp_path, "", "").strip() == ""


def test_the_header_reads_the_image_the_scan_runs():
    """Header and compose must name one image, or the build line describes another.

    Upstream's copy names `auditware`, which this fork neither pulls nor runs;
    on a machine that has both cached it reported the wrong build silently. Tied
    to compose rather than to a literal so the next upstream merge that brings
    the name back fails here instead of in a scan header nobody reads.
    """
    source = RADAR.read_text()
    compose = (RADAR.parent / "docker-compose.yml").read_text()
    header_image = re.search(
        r'print_version\(\) \{.*?local image="([^"]+)"', source, re.S
    ).group(1)
    assert header_image in compose


def test_an_unparseable_date_says_nothing(tmp_path):
    """Never let a cosmetic header break a scan."""
    assert _run(tmp_path, "abc1234", "not-a-date").strip() == ""
