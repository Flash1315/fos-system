import os
from pathlib import Path

# Ensure app settings bind to an isolated DB before any app import.
_db = Path("/tmp") / "fos-pytest.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ.setdefault("SECRET_KEY", "test-secret")
