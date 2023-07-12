from dataclasses import dataclass
import hashlib
import json
import os
import re
import sys
from enum import Enum
import subprocess as sp
import tempfile

import yaml

package_spec_pattern = re.compile(r"(?P<package>[^=><\s]+)(\s*)(?P<constraint>.+)?")


class PackageManager(Enum):
    """Enum of supported package managers."""

    MAMBA = "mamba"
    CONDA = "conda"


@dataclass
class Environment:
    path: str

    @property
    def name(self):
        return os.path.basename(self.path)


@dataclass
class InjectedEnvironment:
    name: str
    package_manager: PackageManager

    def remove(self):
        """Remove the environment."""
        sp.run(
            [self.package_manager.value, "env", "remove", "-n", self.name, "-y"],
            check=True,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.remove()


def inject_packages(
    channels: list[str],
    packages: list[str],
    package_manager: PackageManager = PackageManager.MAMBA,
) -> InjectedEnvironment:
    """Inject conda packages into the current environment.

    Args:
        channels: List of channels to search for packages.
        packages: List of packages to install.
    """
    env = {
        "channels": channels,
        "dependencies": packages,
    }

    return inject_env(env, package_manager)


def inject_env(
    env: dict[str, list], package_manager: PackageManager = PackageManager.MAMBA
) -> InjectedEnvironment:
    """Inject conda packages into the current environment.

    Args:
        env: Environment to inject, given as dict with the keys `channels` and
             `dependencies`. The expected values are the same as for conda
             `environment.yml` files.
    """
    _check_env(env)

    # inject python with same version as current environment
    python_package = f"python ={sys.version_info.major}.{sys.version_info.minor}"
    env["dependencies"].append(python_package)

    checksum = hashlib.sha256()
    checksum.update(json.dumps(env).encode("utf-8"))
    env_checksum = checksum.hexdigest()
    env_name = f"conda-inject-{env_checksum}_"

    envs = _get_envs(package_manager)

    if env_name not in envs:
        with tempfile.NamedTemporaryFile(suffix=".conda.yaml", mode="w") as tmp:
            yaml.dump(env, tmp)
            tmp.flush()
            cmd = [
                package_manager.value,
                "env",
                "create",
                "--name",
                env_name,
                "-f",
                tmp.name,
            ]
            sp.run(cmd, check=True, stdout=sp.PIPE, stderr=sp.PIPE)

    _inject_path(env_name, package_manager)
    return InjectedEnvironment(name=env_name, package_manager=package_manager)


def _inject_path(env_name: str, package_manager: PackageManager):
    envs = _get_envs(package_manager)
    env = envs[env_name]

    sys.path.append(
        f"{env.path}/lib/"
        f"python{sys.version_info.major}.{sys.version_info.minor}/"
        "site-packages"
    )


def _get_envs(package_manager: PackageManager) -> set[str]:
    envs = json.loads(
        sp.run(
            [package_manager.value, "env", "list", "--json"],
            check=True,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        ).stdout.decode()
    )["envs"]
    return {env.name: env for env in map(Environment, envs)}


def _check_env(env: dict[str, list]) -> bool:
    """Check if the given environment is valid."""
    if "channels" not in env:
        raise ValueError("Missing 'channels' in environment.")
    if "dependencies" not in env:
        raise ValueError("Missing 'dependencies' in environment.")
    _check_packages(env["dependencies"])


def _check_packages(packages):
    """Check if the given package specs are valid."""
    for package_spec in packages:
        m = package_spec_pattern.match(package_spec)
        if m:
            if m.group("package") == "python":
                raise ValueError(
                    "The list of packages contains python. "
                    "This is not allowed as conda-inject automatically "
                    "chooses a python version matching to the current "
                    "environment."
                )
        else:
            raise ValueError(
                "Invalid package spec. Must be of the form "
                "'mypackage=1.0.0' or 'mypackage>=1.0.0'"
            )
