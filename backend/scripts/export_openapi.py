"""Write the OpenAPI document used to generate frontend types.

Usage (from backend/): PYTHONPATH=. uv run python scripts/export_openapi.py ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import create_app

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
target.write_text(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n", "utf-8")
print(f"wrote {target}")
