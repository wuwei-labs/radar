import os
from pathlib import Path
import yaml
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from utils.selection import template_applies
from api.models import GeneratedAST
from api.tasks import run_scan_task
from utils.ast import (
    generate_program_ast_for_folder,
    generate_ast_for_rust_file,
)
from celery.result import AsyncResult


from .serializers import GenerateASTSerializer

import logging

logger = logging.getLogger(__name__)


# How many AST rows to keep per project.
#
# This table used to be bounded by tearing the stack down and deleting its
# volumes before every scan, which is also why two scans could never overlap.
# Bounding it per project instead means that wipe is no longer load-bearing.
# The headroom is deliberate: a project with several scans in flight must never
# have a live row pruned out from under it.
AST_HISTORY_PER_PROJECT = 10


def scoped_query(params, source_type, source_path):
    """Look up AST rows by who asked for them, not only by where they live.

    `source_path` is a path *inside* the container, so it is `/contract` for
    every caller and identifies nothing on its own. The project and scan ids
    narrow it to the run that actually generated the row.

    Both are optional. A CLI predating them sends neither and gets the old
    path-only behaviour, which is correct for the one-scan-at-a-time use it was
    written for.
    """
    query = {"source_type": source_type, f"{source_type}_path": source_path}
    for key in ("project_id", "scan_id"):
        value = params.get(key)
        if value:
            query[key] = value
    return query


def prune_ast_history(project_id):
    """Drop this project's oldest AST rows, keeping the newest few.

    Scoped to one project, so a scan can only ever shrink its own history —
    the property the global volume wipe did not have.
    """
    if not project_id:
        return
    keep = list(
        GeneratedAST.objects.filter(project_id=project_id)
        .order_by("-created")
        .values_list("id", flat=True)[:AST_HISTORY_PER_PROJECT]
    )
    GeneratedAST.objects.filter(project_id=project_id).exclude(id__in=keep).delete()


class GenerateASTView(APIView):
    def post(self, request, *args, **kwargs):
        source_type = request.data.get("source_type")
        source_path = request.data.get(f"{source_type}_path")
        project_id = request.data.get("project_id")
        scan_id = request.data.get("scan_id")
        framework = request.data.get("framework", "unknown")
        protocols = request.data.get("protocols", []) or []
        # Test code is written unsafely on purpose, so it is out of scope by
        # default; `radar --include-tests` puts it back. Absent field means
        # exclude, so an older controller talking to a newer API gets the
        # default rather than silently keeping the noise.
        include_tests = bool(request.data.get("include_tests", False))

        if not source_type or not source_path:
            return Response(
                {"error": "Missing required fields: source_type and path"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if source_type not in ["file", "folder"]:
            logger.error(f"Unrecognized source_type {source_type}")
            return Response(
                {"error": 'source_type must be either "file" or "folder"'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        source_file_path = Path("/radar_data") / Path(source_path.lstrip("/"))
        
        language = "rust"
        if source_type == "file" and source_file_path.suffix == ".sol":
            language = "solidity"
        
        logger.info(f"Language detected: {language}")
        
        if language == "solidity":
            from utils.ast import generate_ast_for_solidity_file
            try:
                file_ast = generate_ast_for_solidity_file(source_file_path)
                ast_data = {"sources": {}, "metadata": {}}
                ast_data = file_ast
            except Exception as e:
                logger.error(e)
                return Response(
                    {"error": f"Failed to parse Solidity AST: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            ast_data = {}

            if source_type == "file":
                logger.info(f"Generating AST for {source_file_path}")
                try:
                    # A file named explicitly by the user is scanned as asked.
                    # `is_test_path` is about walking a tree; pointing radar at
                    # one file and getting nothing back would be the silent
                    # empty scan this feature must not introduce.
                    file_ast = generate_ast_for_rust_file(
                        source_file_path, include_tests=True
                    )
                    ast_data = {"sources": {}, "metadata": {}}
                    ast_data["sources"][str(source_file_path)] = file_ast
                except Exception as e:
                    logger.error(e)
                    return Response(
                        {"error": "Failed to parse AST from provided source code"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            elif source_type == "folder":
                # Check for Solidity files first - only in src/ for Foundry projects
                if (source_file_path / "foundry.toml").exists():
                    # For Foundry projects, only compile src/ files
                    sol_files = list((source_file_path / "src").rglob("*.sol")) if (source_file_path / "src").exists() else []
                else:
                    # For non-Foundry, include all .sol files
                    sol_files = list(source_file_path.rglob("*.sol"))
                
                # Filter out Foundry test/verification files (only for Foundry projects)
                if (source_file_path / "foundry.toml").exists():
                    sol_files = [
                        f for f in sol_files 
                        if not any(part in f.parts for part in ['test', 'Test', 'certora', 'forge-std'])
                        and not f.stem.endswith('.t')
                    ]
                
                if sol_files:
                    logger.info(f"Found {len(sol_files)} Solidity file(s) at {source_file_path}")
                    language = "solidity"
                    logger.info(f"Language detected: {language}")
                    from utils.solidity_compiler import get_foundry_remappings, compile_solidity_files
                    
                    remappings = None
                    base_path = None
                    
                    if (source_file_path / "foundry.toml").exists():
                        logger.info("Detected Foundry project, extracting remappings...")
                        from utils.solidity_compiler import prepare_foundry_project
                        prepare_foundry_project(source_file_path)
                        remappings = get_foundry_remappings(source_file_path)
                        base_path = source_file_path
                    
                    try:
                        # Compile all files together for proper import resolution
                        compiled_ast = compile_solidity_files(sol_files, remappings=remappings, base_path=base_path)
                        ast_data = compiled_ast
                    except Exception as e:
                        logger.error(e)
                        return Response(
                            {"error": f"Failed to parse Solidity AST: {str(e)}"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                # User may provide a path to the root of the project, to a
                # specific program, or to a folder holding several - the shared
                # dispatch in `ast.py` decides which, so the offline harnesses
                # scan a folder exactly the way this endpoint does.
                else:
                    try:
                        ast_data = generate_program_ast_for_folder(
                            source_file_path, include_tests
                        )
                    except Exception as e:
                        logger.error(e)
                        return Response(
                            {
                                "error": f"Failed to process source path {source_file_path}: {str(e)}"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

        serializer_data = {
            "ast": ast_data,
            "source_type": source_type,
            "file_path": source_path if source_type == "file" else None,
            "folder_path": source_path if source_type == "folder" else None,
            "language": language,
            "framework": framework,
            "protocols": protocols,
            "project_id": project_id,
            "scan_id": scan_id,
        }
        serializer = GenerateASTSerializer(data=serializer_data)

        if serializer.is_valid():
            serializer.save()
            # Prune after the row is written, not before: a scan that fails to
            # produce an AST should not shorten the history of one that did.
            prune_ast_history(project_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RunScanView(APIView):
    def post(self, request, *args, **kwargs):
        source_type = request.data.get("source_type")
        source_path = request.data.get(f"{source_type}_path")
        templates_path = request.data.get("templates_path")

        if not source_path or not source_type:
            return Response(
                {"error": "Missing source type or path"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if templates_path:
            # Handle both absolute and relative template paths
            if Path(templates_path).is_absolute():
                templates_path = Path("/radar_data") / Path(templates_path).relative_to("/")
            else:
                templates_path = Path("/radar_data") / templates_path
            if not templates_path.exists() or not templates_path.is_dir():
                return Response(
                    {"error": "Invalid templates path"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            yaml_files = list(templates_path.rglob("*.yaml"))
        else:
            templates_path = Path("builtin_templates").absolute()
            yaml_files = list(templates_path.rglob("*.yaml"))

        if not yaml_files:
            return Response(
                {"error": "No YAML files found at the specified templates path"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_ids = []
        scan_id = request.data.get("scan_id")
        query = scoped_query(request.data, source_type, source_path)
        generated_ast = (
            GeneratedAST.objects.filter(**query).order_by("-created").first()
        )

        if generated_ast is None:
            # Previously this raised an AttributeError further down and returned
            # a 500. With scoped lookups a miss is a real, reachable case — the
            # AST belongs to a different project — so say so.
            return Response(
                {"error": "No GeneratedAST found for this scan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get the detected language and framework from the AST
        detected_language = generated_ast.language if generated_ast else "rust"
        detected_framework = generated_ast.framework if generated_ast else "unknown"
        detected_protocols = set(getattr(generated_ast, "protocols", None) or [])

        for yaml_file in yaml_files:
            yaml_data = None
            try:
                with open(yaml_file, "r") as f:
                    yaml_data = yaml.safe_load(f)
            except:
                return Response(
                    {"error": f"Invalid template provided: {yaml_file}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if yaml_data is not None:
                # accent + protocol selection; see api/utils/selection.py for
                # why an accent is a floor rather than an exact match.
                if not template_applies(
                    yaml_data,
                    detected_language,
                    detected_framework,
                    detected_protocols,
                ):
                    continue

                # The template name alone used to be the task id, which made it
                # global across every scan on the machine: two projects running
                # the same rule at once collided in the result backend and one
                # read the other's findings. Namespacing by scan makes the id
                # unique per run while staying readable in celery's logs.
                task_id = (
                    f"{scan_id}:{yaml_data['name']}" if scan_id else yaml_data["name"]
                )
                result = run_scan_task.apply_async(
                    kwargs={
                        "yaml_data": yaml_data,
                        "generated_ast_id": generated_ast.id,
                    },
                    task_id=task_id,
                )
                task_ids.append(result.id)

        generated_ast.task_ids = task_ids
        generated_ast.save()

        return Response({"message": "Scan initiated"}, status=status.HTTP_201_CREATED)


class PollResultsView(APIView):
    def get(self, request, *args, **kwargs):
        source_type = request.GET.get("source_type")
        source_path = request.GET.get(f"{source_type}_path")

        # Validate the required parameters
        if not source_type or not source_path:
            return Response(
                {"error": "Missing required fields: source_type and path"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = scoped_query(request.GET, source_type, source_path)
        generated_ast = (
            GeneratedAST.objects.filter(**query).order_by("-created").first()
        )

        if not generated_ast:
            return Response(
                {"error": "GeneratedAST not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        results = []
        errors = []
        all_done = True

        for task_id in generated_ast.task_ids:
            result = AsyncResult(task_id)
            if result.ready():
                if result.successful():
                    task_result = result.get() or {}
                    # A template that raised records its error but keeps the
                    # scan going, so one broken rule no longer discards every
                    # other finding.
                    if task_result.get("error"):
                        errors.append(
                            {"name": task_result.get("name", task_id),
                             "error": task_result["error"]}
                        )
                    task_result_results = task_result.get("results")
                    if task_result_results and (
                        task_result_results.get("locations")
                        or task_result_results.get("debug")
                    ):
                        results.append(task_result_results)
                else:
                    # An unexpected worker-level failure (e.g. the process was
                    # killed) is surfaced as an error, not swallowed and not a
                    # hard abort of the whole scan.
                    errors.append(
                        {"name": task_id, "error": str(result.result)}
                    )
            else:
                all_done = False

        if all_done:
            template_count = len(generated_ast.task_ids)
            return Response({
                "results": results,
                "template_count": template_count,
                "errors": errors,
            }, status=status.HTTP_200_OK)
        else:
            return Response(
                {"status": "Tasks are still running."}, status=status.HTTP_202_ACCEPTED
            )
