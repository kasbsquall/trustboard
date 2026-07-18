"""Loads a DataHub datapack on Windows, working around a CLI bug.

The bug: `datahub datapack load` downloads the datapack JSON files to a local
path like `C:\\Users\\...\\file.json` and the FileSource ingests them. To
resolve the filesystem, the CLI calls `urllib.parse.urlparse(path).scheme`, and
on Windows the drive letter `C:` is interpreted as the scheme `c`. Since there
is no filesystem registered for `c`, it blows up with:

    KeyError: 'Did not find a registered class for c'

The fix: treat any single-letter scheme (a Windows drive) as a local `file`
path. No real filesystem scheme (file, http, https, s3) is a single letter, so
the patch is safe. After patching, the same official `datapack load` is
invoked, preserving the loader's time-shift and file ordering.

Usage:
    python scripts/load_datapack.py showcase-ecommerce [--force]
"""
from __future__ import annotations

import sys
from urllib import parse

import datahub.ingestion.fs.fs_base as fs_base
import datahub.ingestion.source.file as source_file


def _patched_get_path_schema(path: str) -> str:
    scheme = parse.urlparse(path).scheme
    # "" = local POSIX path; len 1 = Windows drive letter (C:, D:, ...)
    if scheme == "" or len(scheme) == 1:
        return "file"
    return scheme


# file.py did `from ...fs_base import get_path_schema`, so the reference has to
# be replaced in both modules.
fs_base.get_path_schema = _patched_get_path_schema
source_file.get_path_schema = _patched_get_path_schema


def main() -> None:
    from datahub.entrypoints import datahub

    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/load_datapack.py <datapack> [--force]")
        raise SystemExit(2)

    sys.argv = ["datahub", "datapack", "load", *args]
    datahub()


if __name__ == "__main__":
    main()
