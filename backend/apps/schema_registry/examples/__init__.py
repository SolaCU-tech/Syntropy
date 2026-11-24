import json
from pathlib import Path
from typing import Any

EXAMPLES_DIR = Path(__file__).resolve().parent
RETAIL_SSD_PATH = EXAMPLES_DIR / "retail.ssd.json"


def load_retail_ssd() -> dict[str, Any]:
    """The hand-written retail example: Customers, Products and Sales, with links."""
    return json.loads(RETAIL_SSD_PATH.read_text(encoding="utf-8"))
