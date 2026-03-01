import shutil
from pathlib import Path

from invoke import task

PYTHON_CMD = "patchedpython" if shutil.which("patchedpython") else "python3"


def _clean(extra_paths=None) -> None:
    paths = ["error", "__pycache__"]
    if extra_paths:
        paths.extend(extra_paths)
    for path in paths:
        p = Path(path)
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()


def _run(c, extra_args=None, clean_before=True) -> None:
    if clean_before and Path("error").exists():
        return

    cmd = [PYTHON_CMD, "app.py"]
    if extra_args:
        cmd.extend(extra_args)

    c.run(" ".join(cmd), pty=True)


@task
def clean(_c, storage=False) -> None:
    """Clean error and cache files. Use --storage to also clean storage."""
    extra = ["storage"] if storage else None
    _clean(extra)


@task(default=True)
def run(c, args="", clean=True) -> None:
    """Run the crawler. Use args='--help' for options."""
    _clean() if clean else None
    extra_args = args.split() if args else []
    _run(c, extra_args, clean_before=False)


@task
def crawl(c, cities="", queries="", salaries="", task_name="") -> None:
    """Run crawler with custom parameters."""
    _clean()
    extra_args = []
    if cities:
        extra_args.append(f"citys='[{cities}]'")
    if queries:
        extra_args.append(f"querys='[{queries}]'")
    if salaries:
        extra_args.append(f"salarys='[{salaries}]'")
    if task_name:
        extra_args.append(f"task={task_name}")
    _run(c, extra_args)


@task
def greet(c, clean=True) -> None:
    """Run greeting task."""
    _clean() if clean else None
    _run(c, ["++task=greet"], clean_before=False)


@task
def ci(c) -> None:
    """Run in CI mode (no cleanup)."""
    _run(c, ["+ci=ci"], clean_before=False)


@task
def test(c) -> None:
    """Run tests or dry run."""
    _run(c, ["--help"], clean_before=False)


@task
def lint(c) -> None:
    """Run linting checks."""
    c.run(f"{PYTHON_CMD} -m ruff check .", pty=True)


@task
def fmt(c) -> None:
    """Format code."""
    c.run(f"{PYTHON_CMD} -m ruff format .", pty=True)


@task
def typecheck(c) -> None:
    """Run type checking."""
    c.run(f"{PYTHON_CMD} -m mypy .", pty=True)
