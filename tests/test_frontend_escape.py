import subprocess
import sys
from pathlib import Path


def test_frontend_escape_regression_script():
    script = Path(__file__).parents[1] / "scripts" / "check_frontend_escape.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout