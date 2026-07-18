"""Read-only SQLite inventory used exclusively by migration Phase 1."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _masked(value: object) -> object:
    if value is None or isinstance(value, (int, float)):
        return value
    text = str(value)
    return {"type": type(value).__name__, "length": len(text), "sha256_prefix": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]}


def audit(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    normalized = str(path.resolve()).replace("\\", "/")
    uri = f"file:{quote(normalized)}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        catalog = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE type IN ('table','view','trigger') ORDER BY type,name").fetchall()
        tables = []
        for kind, name, table_name, sql in catalog:
            if kind != "table" or name.startswith("sqlite_"):
                continue
            columns = connection.execute(f"PRAGMA table_info({_quote(name)})").fetchall()
            foreign_keys = connection.execute(f"PRAGMA foreign_key_list({_quote(name)})").fetchall()
            index_rows = connection.execute(f"PRAGMA index_list({_quote(name)})").fetchall()
            indexes = [{"name": row[1], "unique": bool(row[2]), "origin": row[3], "partial": bool(row[4]), "columns": [item[2] for item in connection.execute(f"PRAGMA index_info({_quote(row[1])})").fetchall()]} for row in index_rows]
            count = connection.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]
            raw_sample = connection.execute(f"SELECT * FROM {_quote(name)} LIMIT 1").fetchone()
            sample = {columns[index][1]: _masked(value) for index, value in enumerate(raw_sample)} if raw_sample else None
            tables.append({"name": name, "row_count": count, "columns": [{"name": row[1], "type": row[2], "not_null": bool(row[3]), "default": row[4], "primary_key_position": row[5]} for row in columns], "foreign_keys": [{"table": row[2], "from": row[3], "to": row[4], "on_update": row[5], "on_delete": row[6]} for row in foreign_keys], "indexes": indexes, "sample_masked": sample})
        return {"path": str(path), "tables": tables, "views": [{"name": name, "table": table_name, "sql": sql} for kind, name, table_name, sql in catalog if kind == "view"], "triggers": [{"name": name, "table": table_name, "sql": sql} for kind, name, table_name, sql in catalog if kind == "trigger"]}
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("source", type=Path); parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(); payload = audit(arguments.source); rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if arguments.output: arguments.output.write_text(rendered, encoding="utf-8")
    else: print(rendered)
