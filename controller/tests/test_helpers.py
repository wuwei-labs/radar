"""Unit tests for the controller's reporting, gating, and baseline logic.

These cover the pure functions and the exit-code contract of print_write_outputs
(disk writes are stubbed) so the CI-gating behaviour can't silently regress.

Run from the controller directory: `python -m pytest tests/`
"""

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers  # noqa: E402


# --- pure helpers ---------------------------------------------------------

@pytest.mark.parametrize(
    "severity,fail_on,expected",
    [
        ("Critical", "low", True),
        ("Low", "low", True),
        ("Low", "high", False),
        ("High", "high", True),
        ("Medium", "high", False),
        ("Critical", "none", False),
        ("High", "critical", False),
        ("Critical", "critical", True),
        ("bogus-severity", "low", True),
    ],
)
def test_meets_fail_threshold(severity, fail_on, expected):
    assert helpers.meets_fail_threshold(severity, fail_on) is expected


def test_location_sort_key_orders_by_file_then_numeric_line():
    locs = ["/a/z.rs:10:1-2", "/a/b.rs:2:5-9", "/a/b.rs:2:1-3", "/a/b.rs:10:1-2"]
    ordered = [l.split("/")[-1] for l in sorted(locs, key=helpers.location_sort_key)]
    assert ordered == ["b.rs:2:1-3", "b.rs:2:5-9", "b.rs:10:1-2", "z.rs:10:1-2"]


def test_baseline_fingerprint_and_apply():
    root = Path("/proj")
    findings = [
        {"name": "R1", "severity": "Low", "certainty": "Low", "description": "d",
         "locations": ["/proj/a.rs:10:3-9", "/proj/b.rs:5:1-2"]},
        {"name": "R2", "severity": "High", "certainty": "High", "description": "d",
         "locations": ["/proj/c.sol:20:1-5"]},
    ]
    fps = [fp for f in findings for fp in helpers.finding_fingerprints(f, root)]
    assert fps[0] == "R1::a.rs:10:3-9"
    remaining = helpers.apply_baseline(findings, set(fps[:2]), root)
    assert [f["name"] for f in remaining] == ["R2"]
    assert remaining[0]["locations"] == ["/proj/c.sol:20:1-5"]


def test_load_baseline_missing_file(tmp_path):
    assert helpers.load_baseline(tmp_path / "nope.json") == set()


# --- exit-code contract ---------------------------------------------------

def _run(results, fail_on="low", errors=None, baseline_path=None, write_baseline=False):
    with mock.patch.object(helpers, "save_json_output", lambda *a, **k: None), \
         mock.patch.object(helpers, "write_sarif_output", lambda *a, **k: None), \
         mock.patch.object(helpers, "save_markdown_output", lambda *a, **k: None), \
         mock.patch("pathlib.Path.mkdir", lambda *a, **k: None), \
         mock.patch("pathlib.Path.write_text", lambda *a, **k: None), \
         mock.patch("builtins.open", mock.mock_open()):
        try:
            helpers.print_write_outputs(
                results, {"sources": {"f": 1}}, False, None, "json", None,
                False, fail_on, errors or [], baseline_path, write_baseline,
            )
            return None
        except SystemExit as exc:
            return exc.code


def _finding(sev):
    return {"name": sev + "F", "severity": sev, "certainty": "Low",
            "description": "d", "locations": ["/a/b.rs:1:1-2"]}


def test_exit_clean_is_zero():
    assert _run([]) == 0


def test_exit_findings_default_low_is_one():
    assert _run([_finding("High")]) == 1


def test_exit_low_finding_with_fail_on_high_is_zero():
    assert _run([_finding("Low")], "high") == 0


def test_exit_fail_on_none_is_zero():
    assert _run([_finding("Critical")], "none") == 0


def test_exit_errors_take_precedence_two():
    assert _run([_finding("High")], "low", [{"name": "T", "error": "boom"}]) == 2
    assert _run([], "low", [{"name": "T", "error": "boom"}]) == 2


def test_write_baseline_exits_zero_without_gating():
    assert _run([_finding("Critical")], write_baseline=True) == 0


# --- scoped copies into the shared volume ---------------------------------

def test_copy_to_docker_mount_copies_a_scoped_file(tmp_path):
    """A --container-path pointing at one file used to be copied from /contract,
    the whole mount, which is a directory: shutil.copy2 raised 'Is a directory'."""
    src = tmp_path / "contract" / "src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("fn main() {}")
    dst = tmp_path / "radar_data" / "contract" / "src" / "lib.rs"

    helpers.copy_to_docker_mount(src / "lib.rs", dst, "file")

    assert dst.read_text() == "fn main() {}"


def test_copy_to_docker_mount_copies_a_scoped_folder(tmp_path):
    src = tmp_path / "contract" / "programs" / "one"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("fn one() {}")
    sibling = tmp_path / "contract" / "programs" / "two"
    sibling.mkdir(parents=True)
    (sibling / "lib.rs").write_text("fn two() {}")
    dst = tmp_path / "radar_data" / "contract" / "programs" / "one"

    helpers.copy_to_docker_mount(src, dst, "folder")

    # Only the scoped program, not its sibling.
    assert (dst / "lib.rs").read_text() == "fn one() {}"
    assert not (dst.parent / "two").exists()


def test_main_copies_the_scoped_path_not_the_whole_mount(monkeypatch):
    """main() derives path_type from --container-path, so it must copy that path.
    Sourcing from /contract failed outright for a file and copied the wrong tree
    for a subdirectory.

    `main` imports controller.api, which pulls in requests and reads env at import
    time. Neither belongs in this suite - it is meant to run on a bare pytest with
    no runtime dependencies - so the module is stubbed at the import boundary.

    The destination is the other half of the pair: what was scoped gets copied,
    and it lands under the calling project's directory rather than the shared
    `/radar_data/contract` every project used to write to."""
    fake_api = types.ModuleType("api")
    # `**k`: the project and scan ids, and the detection path, travel by keyword.
    fake_api.generate_ast_for_file_or_folder = lambda *a, **k: {"ast": {}}
    fake_api.run_scan = lambda *a, **k: None
    fake_api.poll_results = lambda *a, **k: ([], [])
    monkeypatch.setitem(sys.modules, "api", fake_api)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415

    scoped = Path("/contract/src/lib.rs")
    copied = []
    monkeypatch.setattr(main, "check_path", lambda path: "file")
    monkeypatch.setattr(
        main, "copy_to_docker_mount", lambda src, dst, kind: copied.append((src, dst))
    )
    monkeypatch.setattr(main, "print_write_outputs", lambda *a, **k: None)
    monkeypatch.setattr(
        main, "parse_arguments", lambda: mock.Mock(
            container_path=str(scoped), output=None, templates=None, path=None,
            ast=False, ignore=None, debug=False, fail_on="low",
            baseline=None, write_baseline=False,
            project_id="proj1", scan_id="run1", store_sarif=False,
        )
    )

    main.main()

    assert copied == [(scoped, Path("/radar_data/proj1/contract/src/lib.rs"))]


# --- a clean scan still writes the promised artefact -----------------------

@pytest.mark.parametrize(
    "output_type,expected",
    [("json", "[]"), ("md", "No results found."), ("sarif", '"version"')],
)
def test_clean_scan_writes_an_empty_output_file(output_type, expected, tmp_path, monkeypatch):
    """radar used to write nothing for json/md when there were no findings, while
    the CLI copied the path out and reported 'Results written to ...' regardless,
    leaving the caller a success message and no file."""
    written = tmp_path / f"output.{output_type}"
    monkeypatch.setattr(
        helpers, "Path", lambda *a: written if str(a[0]).startswith("/radar_data/output") else Path(*a)
    )

    with mock.patch.object(helpers, "container_output_file_path", written, create=True):
        try:
            helpers.print_write_outputs(
                [], {"sources": {"f": 1}}, False, None, output_type, None,
                False, "low", [], None, False,
            )
        except SystemExit as exc:
            assert exc.code == 0

    assert written.exists(), f"no {output_type} file written for a clean scan"
    assert expected in written.read_text()

# --- per-project path scoping --------------------------------------------

def _located(path):
    return [{"name": "R", "locations": [f"{path}:12:3-9"]}]


def test_localize_strips_the_project_scoped_container_root():
    """A location under this scan's staging directory maps back to the caller.

    The root used to be `/radar_data/contract` for every project, and was
    stripped by dropping three fixed path components. Staging per project makes
    that depth wrong, so the root is now removed by name.
    """
    results = _located("/radar_data/ab12cd34/contract/programs/thread/src/lib.rs")
    localized = helpers.localize_results(
        results,
        Path("/home/me/proj"),
        Path("/radar_data/ab12cd34/contract"),
    )
    assert localized[0]["locations"] == [
        "/home/me/proj/programs/thread/src/lib.rs:12:3-9"
    ]


def test_localize_falls_back_when_a_location_escapes_the_root():
    """A location outside the root must not raise mid-report.

    `relative_to` throws rather than returning None, and the findings are
    already computed by this point — degrading to the old fixed-depth strip
    beats losing the whole report.
    """
    results = _located("/radar_data/other/contract/src/lib.rs")
    localized = helpers.localize_results(
        results,
        Path("/home/me/proj"),
        Path("/radar_data/ab12cd34/contract"),
    )
    assert localized[0]["locations"] == ["/home/me/proj/contract/src/lib.rs:12:3-9"]


def test_localize_without_a_root_keeps_the_original_behaviour():
    """No root passed — an older caller — still gets the fixed-depth strip."""
    results = _located("/radar_data/contract/src/lib.rs")
    localized = helpers.localize_results(results, Path("/home/me/proj"))
    assert localized[0]["locations"] == ["/home/me/proj/src/lib.rs:12:3-9"]


def test_reports_are_written_under_the_run_directory(tmp_path):
    """Two scans overlapping must not write to the same report path."""
    written = {}

    def capture(path, findings):
        written["path"] = Path(path)

    with mock.patch.object(helpers, "save_json_output", capture), \
         mock.patch("builtins.open", mock.mock_open()):
        with pytest.raises(SystemExit):
            helpers.print_write_outputs(
                [_finding("High")], {"sources": {"f": 1}}, False, None, "json",
                None, False, "none", [], None, False,
                output_root=tmp_path / "proj" / "run-1",
            )

    assert written["path"] == tmp_path / "proj" / "run-1" / "output.json"
