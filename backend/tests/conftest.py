import os
import sys
import tempfile
from pathlib import Path

# Point the vault and cache at a throwaway directory *before* anything imports
# settings — otherwise a test run would write into the developer's real state.
_TMP = tempfile.mkdtemp(prefix="ufeu-tests-")
os.environ["UFEU_STATE_DIR"] = _TMP
os.environ.pop("UFEU_DEMO", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from ufeu.models import SearchQuery  # noqa: E402


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery(q="nikon d750", limit=10)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"
