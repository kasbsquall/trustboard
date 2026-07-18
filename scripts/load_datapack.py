"""Carga un datapack de DataHub en Windows, sorteando un bug de la CLI.

El bug: `datahub datapack load` descarga los JSON del datapack a una ruta
local tipo `C:\\Users\\...\\file.json` y el FileSource los ingesta. Para
resolver el filesystem, la CLI hace `urllib.parse.urlparse(path).scheme`, y
en Windows la letra de unidad `C:` se interpreta como el scheme `c`. Como no
existe un filesystem registrado para `c`, revienta con:

    KeyError: 'Did not find a registered class for c'

El fix: tratar cualquier scheme de una sola letra (una unidad de Windows)
como ruta local `file`. Ningun scheme real de filesystem (file, http, https,
s3) tiene una sola letra, asi que el parche es seguro. Despues del parche se
invoca el mismo `datapack load` oficial, conservando el time-shift y el orden
de archivos del loader.

Uso:
    python scripts/load_datapack.py showcase-ecommerce [--force]
"""
from __future__ import annotations

import sys
from urllib import parse

import datahub.ingestion.fs.fs_base as fs_base
import datahub.ingestion.source.file as source_file


def _patched_get_path_schema(path: str) -> str:
    scheme = parse.urlparse(path).scheme
    # "" = ruta local POSIX; len 1 = letra de unidad Windows (C:, D:, ...)
    if scheme == "" or len(scheme) == 1:
        return "file"
    return scheme


# file.py hizo `from ...fs_base import get_path_schema`, asi que hay que
# reemplazar la referencia en ambos modulos.
fs_base.get_path_schema = _patched_get_path_schema
source_file.get_path_schema = _patched_get_path_schema


def main() -> None:
    from datahub.entrypoints import datahub

    args = sys.argv[1:]
    if not args:
        print("Uso: python scripts/load_datapack.py <datapack> [--force]")
        raise SystemExit(2)

    sys.argv = ["datahub", "datapack", "load", *args]
    datahub()


if __name__ == "__main__":
    main()
