import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tomllib
import venv

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_supported_install_explicitly_selects_local_sdk():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "omp-rpc==0.1.0" in metadata["project"]["dependencies"]
    assert not any("codeload.github.com" in item for item in metadata["project"]["dependencies"])
    runtime = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
    assert "./vendor/omp/sdk/python/omp-rpc" in runtime.splitlines()
    assert "-e ." in runtime.splitlines()
    tests = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    assert "-r requirements-runtime.txt" in tests.splitlines()


@pytest.mark.skipif(not os.environ.get("CAPRI_INSTALL_WHEELHOUSE"),
                    reason="opt-in fresh-venv offline install; set CAPRI_INSTALL_WHEELHOUSE")
def test_fresh_offline_install_from_checkout_with_spaces_and_unicode(tmp_path):
    wheelhouse = str(Path(os.environ["CAPRI_INSTALL_WHEELHOUSE"]).resolve())
    checkout = tmp_path / "Capri копія з пробілами"
    checkout.mkdir()
    for name in ["pyproject.toml", "requirements-runtime.txt", "requirements-test.txt"]:
        shutil.copy2(ROOT / name, checkout / name)
    shutil.copytree(ROOT / "src", checkout / "src", ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"))
    shutil.copytree(ROOT / "vendor/omp/sdk/python/omp-rpc", checkout / "vendor/omp/sdk/python/omp-rpc",
                    ignore=shutil.ignore_patterns("*.egg-info", "__pycache__", "build"))
    environment = tmp_path / "fresh-venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_FIND_LINKS=wheelhouse,
               PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONUTF8="1")
    # Negative control: this wheelhouse cannot silently supply some other omp-rpc.
    rejected = subprocess.run([str(python), "-m", "pip", "install", "--no-cache-dir",
                               "omp-rpc==0.1.0"], cwd=checkout, env=env,
                              capture_output=True, text=True, timeout=30)
    assert rejected.returncode != 0
    assert "No matching distribution found for omp-rpc==0.1.0" in rejected.stderr
    result = subprocess.run([str(python), "-m", "pip", "install", "--no-cache-dir",
                             "-r", "requirements-test.txt"], cwd=checkout, env=env,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    probe = subprocess.run([str(python), "-c",
        "import importlib.metadata as m,json; print(m.distribution('omp-rpc').read_text('direct_url.json'))"],
        cwd=checkout, env=env, capture_output=True, text=True, check=True)
    origin = json.loads(probe.stdout)
    assert origin["url"] == (checkout / "vendor/omp/sdk/python/omp-rpc").as_uri()
    assert "dir_info" in origin
    subprocess.run([str(python), "-m", "pip", "check"], env=env, check=True, capture_output=True)
