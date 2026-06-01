"""
SentryPay — Pytest Configuration
===================================
Mocks all external dependencies (vertexai, google-cloud, elasticsearch,
colorama, langfuse) before any test imports happen.

This allows unit tests to run without real credentials or network
access, and without the full set of production packages installed.
"""

import sys
from unittest.mock import MagicMock, patch


# ── Pre-mock all heavy external dependencies ──────────────────────────────────
# These must be mocked BEFORE agent modules are imported,
# otherwise the top-level imports in tools.py etc. will fail.

def _make_mock(name):
    """Create a MagicMock module with the given name."""
    mock = MagicMock()
    mock.__name__  = name
    mock.__spec__  = None
    return mock


# Google Cloud / Vertex AI
sys.modules.setdefault("vertexai",                                _make_mock("vertexai"))
sys.modules.setdefault("vertexai.language_models",               _make_mock("vertexai.language_models"))
sys.modules.setdefault("vertexai.generative_models",             _make_mock("vertexai.generative_models"))
sys.modules.setdefault("google",                                  _make_mock("google"))
sys.modules.setdefault("google.cloud",                            _make_mock("google.cloud"))
sys.modules.setdefault("google.cloud.bigquery",                   _make_mock("google.cloud.bigquery"))
sys.modules.setdefault("google.cloud.secretmanager",              _make_mock("google.cloud.secretmanager"))
sys.modules.setdefault("google.genai",                            _make_mock("google.genai"))
sys.modules.setdefault("google.genai.types",                      _make_mock("google.genai.types"))
sys.modules.setdefault("google.api_core",                         _make_mock("google.api_core"))
sys.modules.setdefault("google.api_core.exceptions",              _make_mock("google.api_core.exceptions"))

# Elasticsearch
sys.modules.setdefault("elasticsearch",                           _make_mock("elasticsearch"))
sys.modules.setdefault("elasticsearch.helpers",                   _make_mock("elasticsearch.helpers"))

# Langfuse
sys.modules.setdefault("langfuse",                                _make_mock("langfuse"))

# Colorama — mock with real-looking strings so color codes don't break tests
colorama_mock          = _make_mock("colorama")
colorama_mock.Fore     = MagicMock()
colorama_mock.Style    = MagicMock()
colorama_mock.init     = MagicMock()
colorama_mock.Fore.RED    = ""
colorama_mock.Fore.GREEN  = ""
colorama_mock.Fore.YELLOW = ""
colorama_mock.Fore.CYAN   = ""
colorama_mock.Style.RESET_ALL = ""
sys.modules.setdefault("colorama", colorama_mock)

# Other optional deps
sys.modules.setdefault("reportlab",                               _make_mock("reportlab"))
sys.modules.setdefault("slowapi",                                 _make_mock("slowapi"))
sys.modules.setdefault("feedparser",                              _make_mock("feedparser"))
sys.modules.setdefault("tqdm",                                    _make_mock("tqdm"))

# FastAPI — allow real import but mock sub-dependencies
try:
    import fastapi   # noqa: F401 — real import is fine
except ImportError:
    sys.modules.setdefault("fastapi", _make_mock("fastapi"))