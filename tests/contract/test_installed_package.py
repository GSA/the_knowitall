import subprocess
import sys
from pathlib import Path


def test_built_wheel_contains_loadable_contract_schemas(tmp_path):
    root = Path(__file__).parents[2]
    wheelhouse = tmp_path / "wheelhouse"
    target = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(wheelhouse)], cwd=root, check=True, capture_output=True)
    wheel = next(wheelhouse.glob("*.whl"))
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)], cwd=tmp_path, check=True, capture_output=True)
    program = """
import json
from importlib.resources import files
from knowitall_contract import validate_manifest, validate_query_request, validate_query_response
from knowitall_updates import UpdateLedger
examples = files('knowitall_contract').joinpath('examples')
validate_manifest(json.loads(examples.joinpath('clean-manifest.json').read_text()))
validate_query_request(json.loads(examples.joinpath('exact-dependency-request.json').read_text()))
validate_query_response(json.loads(examples.joinpath('dependency-response.json').read_text()))
"""
    subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(target)!r});" + program], cwd=tmp_path, check=True)
