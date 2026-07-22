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


def test_package_data_excludes_python_bytecode() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["setuptools"]["packages"]["find"]["exclude"] == [
        "*.__pycache__",
    ]
    assert config["tool"]["setuptools"]["package-data"]["src.api"] == [
        "templates/**/*.html",
        "static/vendor/**/*",
    ]
    assert config["tool"]["setuptools"]["exclude-package-data"]["*"] == [
        "**/__pycache__/*",
        "**/*.pyc",
    ]


def test_source_distribution_excludes_python_bytecode() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")

    assert "global-exclude *.py[cod]" in manifest
