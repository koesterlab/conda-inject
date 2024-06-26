from pathlib import Path
from conda_inject import inject_env, inject_packages, inject_env_file


def test_env_inject():
    env = {"channels": ["conda-forge"], "dependencies": ["humanfriendly =10.0"]}
    with inject_env(env):
        import humanfriendly  # noqa F401


def test_package_inject():
    with inject_packages(channels=["conda-forge"], packages=["humanfriendly =10.0"]):
        import humanfriendly  # noqa F401


def test_env_file_inject():
    with inject_env_file(Path("tests/test-env.yaml")):
        import humanfriendly  # noqa F401


def test_pip():
    with inject_env_file(Path("tests/test-env-pip.yaml")):
        import humanfriendly  # noqa F401


def test_env_inject_with_constraints():
    env = {"channels": ["conda-forge"], "dependencies": ["humanfriendly =10.0"]}
    with inject_env(env, with_constraints=["requests =2.31"]):
        import humanfriendly  # noqa F401
        import requests  # noqa F401
