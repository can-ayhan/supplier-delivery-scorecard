"""Settings come from the environment, with a local .env file as fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
REFERENCE_DIR = ROOT / "data" / "reference"
SQL_DIR = ROOT / "sql"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    return Settings(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5433")),
        database=os.environ.get("PGDATABASE", "scorecard"),
        user=os.environ.get("PGUSER", "scorecard"),
        password=os.environ.get("PGPASSWORD", "scorecard"),
    )
