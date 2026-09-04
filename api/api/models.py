from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils.translation import gettext_lazy as _


class ScoreLevel(models.TextChoices):
    INFO = "Info", _("Info")
    LOW = "Low", _("Low")
    MEDIUM = "Medium", _("Medium")
    HIGH = "High", _("High")
    CRITICAL = "Critical", _("Critical")


class GeneratedAST(models.Model):
    ast = models.JSONField(blank=True, null=True)
    file_path = models.CharField(max_length=255, blank=True, null=True)
    folder_path = models.CharField(max_length=255, blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True, null=True)
    task_ids = ArrayField(models.CharField(max_length=255), blank=True, null=True)
    language = models.CharField(max_length=50, default="rust", blank=True, null=True)
    framework = models.CharField(max_length=50, default="unknown", blank=True, null=True)
    # Protocols this source integrates with (squads, metaplex, antegen, ...),
    # read from the same manifests the framework comes from. A template carrying
    # a `protocol` runs only when that protocol is listed here.
    protocols = ArrayField(
        models.CharField(max_length=50), blank=True, null=True, default=list
    )

    # Which project this AST belongs to: a stable hash of the caller's path on
    # the host, computed by the CLI.
    #
    # Rows used to be identified by `folder_path` alone, which is the path
    # *inside* the container — always `/contract`, for every caller. Two
    # projects scanning at once therefore wrote rows that looked identical, and
    # the newest-first lookup handed one project the other's AST. Keying on the
    # caller is what makes a scan see only its own work.
    #
    # Nullable so rows written before this field existed still load, and so an
    # older CLI that does not send an id keeps working against a newer API.
    project_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    # Which run within that project. Two scans of the same directory — two
    # worktrees, two commits in flight — share a project_id and must still not
    # read each other's rows.
    scan_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    class SourceTypeOptions(models.TextChoices):
        FILE = "file"
        FOLDER = "folder"

    source_type = models.CharField(choices=SourceTypeOptions.choices)

    def __str__(self):
        if self.source_type == self.SourceTypeOptions.FILE:
            return self.file_path if self.file_path else "Bad filepath"
        else:
            return self.folder_path if self.folder_path else "Bad folderpath"