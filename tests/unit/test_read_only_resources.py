import hashlib
import json
from importlib.resources import files
from pathlib import Path


def test_vendor_files_match_manifest_and_have_licenses() -> None:
    root = files("src.api.static")
    manifest = json.loads(files("src.resources").joinpath("vendor_hashes.json").read_text())
    for relative, expected in manifest.items():
        payload = root.joinpath(relative).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected
    assert root.joinpath("vendor/htmx-2.0.10/LICENSE.txt").is_file()
    assert root.joinpath("vendor/echarts-5.5.1/LICENSE.txt").is_file()


def test_mvp_has_one_baseline_and_no_activation_assets() -> None:
    baseline = json.loads(
        files("src.resources").joinpath("detectors/baseline.json").read_text(encoding="utf-8")
    )
    assert baseline["version"] == "baseline-v1"
    assert baseline["max_claims"] == 10
    assert baseline["temperature"] == 0
    assert not Path("runtime/detectors").exists()
    assert not Path("active.json").exists()
