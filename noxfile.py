import shutil
from pathlib import Path

import nox

configs = [""]
python_cmd = "patchedpython" if shutil.which("patchedpython") else "python"


def run_clean(session, extra_paths=None):
    if extra_paths is None:
        extra_paths = []
    for path in ["error", "__pycache__", *extra_paths]:
        if Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)


def run_base(session: nox.session, extra_args=None):
    if Path("error").exists():
        session.error()
    cmd = [python_cmd, "app.py"]
    if extra_args:
        cmd.extend(extra_args)
    session.run(*cmd, external=True)


@nox.session(venv_backend="none")
def clean(session):
    run_clean(session, ["storage"])


@nox.session(venv_backend="none")
def default(session):
    run_clean(session)
    run_base(session, session.posargs)


@nox.session(venv_backend="none")
def rotation(session):
    run_clean(session)
    while True:
        for config in configs:
            extra_args = []
            if config:
                extra_args.append(f"+config={config}")
            run_base(session, extra_args)


@nox.session(venv_backend="none")
def greet(session):
    run_clean(session)
    for config in configs:
        extra_args = ["++task=greet"]
        if config:
            extra_args.append(f"+config={config}")
        run_base(session, extra_args)
