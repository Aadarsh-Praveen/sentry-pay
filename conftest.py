# Root conftest.py — ensures pytest adds project root to sys.path
import sys
from pathlib import Path

# Add project root to path so 'agent', 'config' etc. are importable
sys.path.insert(0, str(Path(__file__).parent))