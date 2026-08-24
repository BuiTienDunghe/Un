"""Archive original sources and a SHA-256 manifest; does not alter source files.

Importable (`archive_sources`) so the nightly backup worker runs exactly the
same code path as a manual run — the same rule backup_postgres follows.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from app.config.settings import get_settings

SOURCES_PATTERN = "sources-*.zip"


def archive_sources(documents_path: Path, output_dir: Path) -> tuple[Path, int]:
    """Zip every `*/original.*` under documents_path with a SHA-256 manifest.

    Written to a .part name and renamed only when complete, so an interrupted
    archive never sits on disk looking like a recovery point.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"sources-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    partial = archive.with_suffix(".zip.part")
    manifest = []
    try:
        with ZipFile(partial, "w", ZIP_DEFLATED) as zip_file:
            for source in sorted(documents_path.glob("*/original.*")):
                data = source.read_bytes()
                relative = source.relative_to(documents_path)
                zip_file.writestr(str(relative), data)
                manifest.append({"path": str(relative), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        partial.replace(archive)
    finally:
        partial.unlink(missing_ok=True)
    return archive, len(manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/backups/sources")
    args = parser.parse_args()
    archive, count = archive_sources(get_settings().documents_path, Path(args.output_dir))
    print(json.dumps({"archive": str(archive), "sources": count}))


if __name__ == "__main__":
    main()
