"""Move RabbitMQ handlers from main.py to handlers.py; keep wiring in runtime.py + thin main.py."""
from __future__ import annotations

import ast
import re
from pathlib import Path

SERVICES = [
    "chat_service",
    "analytics_service",
    "group_service",
    "notification_service",
    "scheduler_service",
]

ROOT = Path(__file__).resolve().parents[1]

COMMON_IMPORTS = {
    "MessageBus": "from common.messaging import MessageBus",
    "MessageError": "from common.messaging import MessageError",
    "MessageWorker": "from common.messaging import MessageWorker",
    "UserContext": "from common.messaging import UserContext",
    "require_user": "from common.messaging import require_user",
    "check_rabbitmq": "from common.messaging import check_rabbitmq",
}
STD_IMPORTS = {
    "Decimal": "from decimal import Decimal",
    "UTC": "from datetime import UTC",
    "date": "from datetime import date",
    "datetime": "from datetime import datetime",
    "Any": "from typing import Any",
    "UUID": "from uuid import UUID",
    "logging": "import logging",
    "json": "import json",
    "text": "from sqlalchemy import text",
    "select": "from sqlalchemy import select",
    "func": "from sqlalchemy import func",
    "sessionmaker": "from sqlalchemy.orm import sessionmaker",
    "Session": "from sqlalchemy.orm import Session",
}


def _runtime_symbols(header: str) -> list[str]:
    names = []
    for line in header.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*) =", line)
        if m:
            name = m.group(1)
            if name in {"settings", "engine", "bus", "worker", "SessionLocal"} or name.endswith("_QUEUE") or name in {
                "SERVICE_NAME",
                "QUEUE_NAME",
            }:
                names.append(name)
    return names


def _collect_imports(handlers_body: str, header: str) -> str:
    tree = ast.parse(handlers_body + "\npass")
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
    lines = ["from __future__ import annotations", ""]
    for key, stmt in STD_IMPORTS.items():
        if key in used:
            lines.append(stmt)
    common = [stmt for key, stmt in COMMON_IMPORTS.items() if key in used]
    if common:
        lines.append("from common.messaging import " + ", ".join(k for k in COMMON_IMPORTS if k in used))
    runtime_names = [n for n in _runtime_symbols(header) if n in used]
    service = None
    if runtime_names:
        # filled by caller
        pass
    return "\n".join(lines), runtime_names, used


def extract(service: str) -> None:
    app_dir = ROOT / "services" / service / "app"
    main_path = app_dir / "main.py"
    text = main_path.read_text(encoding="utf-8")
    if "\ndef handle_" not in text:
        print(f"skip {service}: no handlers")
        return
    idx = text.index("\ndef handle_")
    header = text[:idx].rstrip()
    tail = text[idx + 1 :]
    registry_idx = tail.index("MESSAGE_HANDLERS = ")
    handlers_body = tail[:registry_idx].rstrip()
    registry_and_rest = tail[registry_idx:]
    registry = registry_and_rest.split("\ndef _ready", maxsplit=1)[0].rstrip()

    runtime_path = app_dir / "runtime.py"
    runtime_path.write_text(header + "\n", encoding="utf-8")

    _, runtime_names, used = _collect_imports(handlers_body, header)
    import_lines = ["from __future__ import annotations", ""]
    for key, stmt in STD_IMPORTS.items():
        if key in used:
            import_lines.append(stmt)
    common_keys = [k for k in COMMON_IMPORTS if k in used]
    if common_keys:
        import_lines.append("from common.messaging import " + ", ".join(common_keys))
    if runtime_names:
        import_lines.append(f"from services.{service}.app.runtime import (")
        import_lines.extend(f"    {name}," for name in runtime_names)
        import_lines.append(")")
    import_lines.append("")

    handlers_path = app_dir / "handlers.py"
    handlers_path.write_text("\n".join(import_lines) + "\n" + handlers_body + "\n\n\n" + registry + "\n", encoding="utf-8")

    thin_main = f'''from __future__ import annotations

from common.messaging import check_rabbitmq
from common.service_app import create_worker_app
from sqlalchemy import text

from services.{service}.app.handlers import MESSAGE_HANDLERS
from services.{service}.app.runtime import SERVICE_NAME, engine, settings, worker


def _ready() -> None:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    check_rabbitmq(settings.rabbitmq_url)


app = create_worker_app(title=SERVICE_NAME, worker=worker, handlers=MESSAGE_HANDLERS, ready_check=_ready)
'''
    main_path.write_text(thin_main, encoding="utf-8")
    print(f"extracted {service}")


if __name__ == "__main__":
    for name in SERVICES:
        extract(name)
