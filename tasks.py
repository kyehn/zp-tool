import shutil
from pathlib import Path

from invoke import task

PYTHON_CMD = "patchedpython" if shutil.which("patchedpython") else "python"
CONFIGS = [""]


def _clean(extra_paths=None):
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


def _run_base(c, extra_args=None):
    if Path("error").exists():
        return

    cmd = [PYTHON_CMD, "app.py"]
    if extra_args:
        cmd.extend(extra_args)

    c.run(" ".join(cmd), pty=True)


@task
def clean(c):
    _clean(["storage"])


@task(default=True)
def run(c, args=""):
    _clean()
    extra_args = args.split() if args else []
    _run_base(c, extra_args)


@task
def rotation(c):
    _clean()
    while True:
        for config in CONFIGS:
            extra_args = []
            if config:
                extra_args.append(f"+config={config}")
            _run_base(c, extra_args)


@task
def greet(c):
    _clean()
    for config in CONFIGS:
        extra_args = ["++task=greet"]
        if config:
            extra_args.append(f"+config={config}")
        _run_base(c, extra_args)
