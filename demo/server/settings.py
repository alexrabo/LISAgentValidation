"""
Settings — all env var configuration in one place.
No os.environ.get() calls outside this module.
"""
import base64
import json
from pathlib import Path

from pydantic_settings import BaseSettings


_DEFAULT_KG_PATH = str(
    Path(__file__).parent.parent / "config" / "clinical_knowledge.json"
)


class Settings(BaseSettings):
    db_path: str = "lims.db"
    kg_json_b64: str | None = None
    # Default: monorepo path (absolute). Task 08 changes this to config/clinical_knowledge.json
    # inside demo/ once the demo is self-contained.
    kg_path: str = _DEFAULT_KG_PATH
    openid_enabled: bool = False
    openid_issuer: str | None = None    # STUB: set for production
    openid_audience: str | None = None  # STUB: set for production
    throttle_rpm: int = 60

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()


def load_knowledge_graph() -> dict:
    """Load KG from KG_JSON_B64 env var (base64) or KG_PATH file. Checked in that order."""
    if settings.kg_json_b64:
        return json.loads(base64.b64decode(settings.kg_json_b64).decode())
    with open(settings.kg_path) as f:
        return json.load(f)
