import sys
import types
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    import pydantic_settings  # noqa: F401
except ModuleNotFoundError:
    shim = types.ModuleType("pydantic_settings")

    class BaseSettings(BaseModel):
        pass

    shim.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = shim
