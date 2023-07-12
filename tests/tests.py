from conda_inject import inject_env, inject_packages


def test_env_inject():
    env = {"channels": ["conda-forge"], "dependencies": ["humanfriendly =10.0"]}
    with inject_env(env):
        import humanfriendly  # noqa F401


def test_package_inject():
    with inject_packages(channels=["conda-forge"], packages=["humanfriendly =10.0"]):
        import humanfriendly  # noqa F401
