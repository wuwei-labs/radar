import sys
from pathlib import Path
from helpers import (
    check_path,
    copy_to_docker_mount,
    parse_arguments,
    print_write_outputs,
)
from api import generate_ast_for_file_or_folder, run_scan, poll_results


def main():
    args = parse_arguments()
    container_path = Path(args.container_path)
    path_type = check_path(container_path)
    output_type = "json"

    # Where this scan is allowed to write.
    #
    # The shared volume used to be flat: every scan staged its source at
    # /radar_data/contract and wrote its report to /radar_data/output.json,
    # under those names, for every project on the machine. Two scans overlapping
    # meant one of them read the other's source and reported on it. Giving each
    # project a directory, and each run a directory inside that, is what makes
    # concurrent scans possible at all.
    #
    # The fallbacks keep a CLI that predates these flags working: it gets one
    # fixed slot, which is all a one-scan-at-a-time caller ever needed.
    project_id = args.project_id or "default"
    scan_id = args.scan_id or "current"
    project_root = Path("/radar_data") / project_id
    # `--store-sarif` accumulates findings into one report across runs, so its
    # report has to outlive the run that wrote it. Per project rather than per
    # scan, which also means two concurrent scans of one project cannot both
    # accumulate — inherent to appending into a single file, and still isolated
    # from every other project.
    output_root = project_root if args.store_sarif else project_root / scan_id
    # The path the API resolves against /radar_data, and the DB key for this
    # scan's AST rows.
    staged_relative = Path(project_id) / container_path.relative_to("/")

    if args.output:
        if args.output.endswith(".sarif"):
            output_type = "sarif"
        elif args.output.endswith(".md"):
            output_type = "md"

    print(f"[i] Copying {path_type} from radar container to a shared docker volume")
    # Copy what was actually scoped, not the whole mount. `--container-path` may point
    # at a single file or a subdirectory inside /contract, and the destination mirrors
    # it; sourcing from /contract copied the wrong tree for a subdirectory and failed
    # outright for a file, since /contract is a directory.
    copy_to_docker_mount(
        container_path,
        # Under this project's own directory, so a scan running alongside cannot
        # overwrite the copy this one is about to be measured against.
        project_root / container_path.relative_to("/"),
        path_type,
    )

    templates_path = None
    if args.templates:
        templates_path = Path(args.templates)
        if not templates_path.exists():
            print(
                f"[e] Provided custom templates folder path {templates_path} is invalid"
            )
            raise FileNotFoundError
        
        # Determine if templates is a file or folder
        templates_type = check_path(Path("/templates"))
        
        if templates_type == "file":
            # For a single file, create templates directory and copy the file into it.
            # Per-project like everything else: this directory is wiped and
            # rewritten below, so a shared one let another project's scan run
            # against whichever template set landed last.
            templates_dir = project_root / "templates"
            
            # Ensure the templates directory exists and is clean
            if templates_dir.exists():
                if templates_dir.is_dir():
                    import shutil
                    shutil.rmtree(templates_dir)
                else:
                    templates_dir.unlink()
            
            templates_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy the single file into the templates directory
            original_filename = args.templates_filename if args.templates_filename else "template.yaml"
            copy_to_docker_mount(
                Path("/templates"),
                templates_dir / original_filename,
                "file",
            )
            templates_path = Path(project_id) / "templates"
            print(f"[i] Using custom provided template file: {original_filename}")
        else:
            copy_to_docker_mount(
                Path("/templates"),
                project_root / "templates",
                "folder",
            )
            templates_path = Path(project_id) / "templates"
            print(f"[i] Using custom provided templates folder.")

    local_path = None
    if args.path:
        local_path = Path(args.path)

    # The API resolves these against /radar_data and stores them as the row key,
    # so it is the staged, project-scoped path that travels — not the bare
    # `/contract` every caller shares.
    ast = generate_ast_for_file_or_folder(
        staged_relative,
        path_type,
        getattr(args, "include_tests", False),
        project_id=project_id,
        scan_id=scan_id,
        detect_path=container_path,
    )
    run_scan(
        staged_relative,
        path_type,
        templates_path,
        project_id=project_id,
        scan_id=scan_id,
    )
    results, errors = poll_results(
        staged_relative,
        path_type,
        local_path,
        project_id=project_id,
        scan_id=scan_id,
        container_root=project_root / container_path.parts[1],
    )

    print_write_outputs(
        results,
        ast["ast"],
        args.ast,
        local_path,
        output_type,
        args.ignore,
        args.debug if hasattr(args, "debug") else False,
        getattr(args, "fail_on", "low"),
        errors,
        "/baseline" if getattr(args, "baseline", None) else None,
        getattr(args, "write_baseline", False),
        output_root=output_root,
    )

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # Intentional exit codes from print_write_outputs (0 clean / 1 findings)
        # and the API-call layer (2 operational). Let them through unchanged.
        raise
    except Exception as exc:
        # Any uncaught failure is an operational error, not a clean run. Exit 2
        # so a CI gate never mistakes a crash for "no findings".
        print(f"[e] radar failed: {exc}")
        sys.exit(2)