import sys
from pathlib import Path

# llama_index is not installed in this environment; load the stub from lib/tests.
sys.path.insert(0, str(Path(__file__).parents[3] / "lib" / "tests" / "stubs"))
