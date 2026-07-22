from pathlib import Path
import tomllib


def test_single_dependency_manifest_and_runtime_ignore() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["requires-python"] == ">=3.11"
    assert set(config["project"]["dependencies"]) == {
        "fastapi>=0.115,<1.0",
        "uvicorn>=0.34,<1.0",
        "pydantic>=2.10,<3.0",
        "jinja2>=3.1,<4.0",
    }
    assert "runtime/" in Path(".gitignore").read_text(encoding="utf-8")
    assert not Path("requirements.txt").exists()
