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


def _run(c, extra_args=None) -> None:
    if Path("error").exists():
        return
    cmd = [PYTHON_CMD, "app.py"]
    if extra_args:
        cmd.extend(extra_args)
    c.run(" ".join(cmd), pty=True)


@task
def clean(_c, storage=False) -> None:
    extra = ["storage"] if storage else None
    _clean(extra)


@task(default=True)
def run(c) -> None:
    _clean()
    _run(c)

@task
def greet(c) -> None:
    _clean()
    _run(c, ["++task=greet"])
