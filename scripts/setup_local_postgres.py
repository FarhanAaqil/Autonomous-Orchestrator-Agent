"""Generate local PostgreSQL credentials without exposing them in output."""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "POSTGRES_DB": "orchestrator",
    "POSTGRES_BOOTSTRAP_USER": "orchestrator_bootstrap",
    "POSTGRES_MIGRATOR_USER": "orchestrator_migrator",
    "POSTGRES_APP_USER": "orchestrator_app",
    "ENVIRONMENT": "development",
    "ALLOW_INSECURE_LOCAL": "false",
    "ACTION_EXECUTION_MODE": "simulation",
}
SECRET_KEYS = (
    "POSTGRES_BOOTSTRAP_PASSWORD",
    "POSTGRES_MIGRATOR_PASSWORD",
    "POSTGRES_APP_PASSWORD",
    "AUTH_TOKEN",
    "EXECUTOR_HMAC_SECRET",
)


def _read_values(contents: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> None:
    original = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    values = _read_values(original)
    additions: list[str] = []

    for key, default in DEFAULTS.items():
        if not values.get(key):
            values[key] = default
            additions.append(f"{key}={default}")

    for key in SECRET_KEYS:
        if not values.get(key):
            values[key] = secrets.token_urlsafe(36)
            additions.append(f"{key}={values[key]}")

    app_url = (
        "postgresql+psycopg://"
        f"{quote(values['POSTGRES_APP_USER'], safe='')}:"
        f"{quote(values['POSTGRES_APP_PASSWORD'], safe='')}"
        f"@postgres:5432/{quote(values['POSTGRES_DB'], safe='')}"
    )
    migration_url = (
        "postgresql+psycopg://"
        f"{quote(values['POSTGRES_MIGRATOR_USER'], safe='')}:"
        f"{quote(values['POSTGRES_MIGRATOR_PASSWORD'], safe='')}"
        f"@postgres:5432/{quote(values['POSTGRES_DB'], safe='')}"
    )

    if not values.get("DATABASE_URL"):
        additions.append(f"DATABASE_URL={app_url}")
    if not values.get("MIGRATION_DATABASE_URL"):
        additions.append(f"MIGRATION_DATABASE_URL={migration_url}")

    if not additions:
        print("PostgreSQL environment entries already exist; nothing changed.")
        return

    separator = "" if not original or original.endswith("\n") else "\n"
    block = "\n# Local PostgreSQL (generated; never commit .env)\n" + "\n".join(additions) + "\n"
    ENV_PATH.write_text(original + separator + block, encoding="utf-8")
    print(f"Wrote {len(additions)} PostgreSQL settings to .env without displaying secrets.")


if __name__ == "__main__":
    main()
