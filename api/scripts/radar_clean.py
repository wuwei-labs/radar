"""Remove radar's cached scan data, for one project or for all of them.

This exists because the CLI used to run `docker compose down -v` before every
single scan. That was the only mechanism bounding the AST table and the shared
volume, and it is why two scans could never overlap: the second one tore down
the stack the first was still using, and on a slow teardown fell back to
`docker system prune -f --volumes`, which reaches every container on the
machine and not just radar's.

Cleaning is now something you ask for. The default asks for one project, so a
reflexive `--clean` can only ever discard your own cached work.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import django

# Run as a file rather than a module, so sys.path[0] is this script's directory
# and the Django project one level up would not otherwise be importable.
sys.path.insert(0, "/api")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from api.models import GeneratedAST  # noqa: E402  (must follow django.setup)

RADAR_DATA = Path("/radar_data")


def remove_tree(path: Path) -> bool:
    """Delete a directory or file, reporting whether there was one."""
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return True


def clean_project(project_id: str) -> None:
    deleted, _ = GeneratedAST.objects.filter(project_id=project_id).delete()
    removed = remove_tree(RADAR_DATA / project_id)
    print(
        f"[i] Cleaned project {project_id}: {deleted} AST row(s), "
        f"{'staged files removed' if removed else 'no staged files'}"
    )


def clean_all() -> None:
    deleted, _ = GeneratedAST.objects.all().delete()
    removed = 0
    if RADAR_DATA.exists():
        for child in RADAR_DATA.iterdir():
            if remove_tree(child):
                removed += 1
    print(f"[i] Cleaned every project: {deleted} AST row(s), {removed} path(s) removed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove radar scan data")
    parser.add_argument(
        "--project-id",
        help="Project whose cached scan data should be removed",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Remove cached scan data for every project on this machine",
    )
    args = parser.parse_args()

    if args.all:
        clean_all()
        return 0

    if not args.project_id:
        # Refusing beats guessing: with no project named, the only thing left to
        # act on is everything, which is exactly what the caller did not ask for.
        print("[e] Provide --project-id, or --all to clean every project.")
        return 2

    clean_project(args.project_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
