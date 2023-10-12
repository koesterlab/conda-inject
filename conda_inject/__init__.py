from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from enum import Enum
import subprocess as sp
import tempfile
from typing import Dict, List, Optional

import yaml

package_spec_pattern = re.compile(r"(?P<package>[^=><\s]+)(\s*)(?P<constraint>.+)?")


class PackageManager(Enum):
    """Enum of supported package managers."""

    MAMBA = "mamba"
    CONDA = "conda"
    MICROMAMBA = "micromamba"


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
    env: Optional[Environment] = None

    def __post_init__(self):
        envs = _get_envs(self.package_manager)
        self.env = envs[self.name]
        self._inject_path()

    def remove(self):
        """Remove the environment."""
        sp.run(
            [self.package_manager.value, "env", "remove", "-n", self.name, "-y"],
            check=True,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        )
        sys.path.remove(self._get_syspath_injection())
        os.environ["PATH"].replace(self._get_path_injection(), "")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.remove()

    def _inject_path(self):
        # manipulate python path
        sys.path.append(self._get_syspath_injection())
        # manipulate PATH
        os.environ["PATH"] = f"{self._get_path_injection()}{os.environ['PATH']}"

    def _get_path_injection(self):
        return f"{self.env.path}/bin:"

    def _get_syspath_injection(self):
        return (
            f"{self.env.path}/lib/"
            f"python{sys.version_info.major}.{sys.version_info.minor}/"
            "site-packages"
        )


def inject_packages(
    channels: List[str],
    packages: List[str],
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
    env: Dict[str, List[str]], package_manager: PackageManager = PackageManager.MAMBA
) -> InjectedEnvironment:
    """Inject conda packages into the current environment.

    Args:
        env: Environment to inject, given as dict with the keys `channels` and
             `dependencies`. The expected values are the same as for conda
             `environment.yml` files.
    """
    _check_env(env)
    _insert_python(env)
    env_name = _get_env_name(env)

    envs = _get_envs(package_manager)

    if env_name not in envs:
        with tempfile.NamedTemporaryFile(suffix=".conda.yaml", mode="w") as tmp:
            yaml.dump(env, tmp)
            tmp.flush()
            _create_env(Path(tmp.name), env_name, package_manager=package_manager)

    return InjectedEnvironment(name=env_name, package_manager=package_manager)


def inject_env_file(
    env_file: Path, package_manager: PackageManager = PackageManager.MAMBA
):
    with open(env_file) as f:
        env = yaml.load(f, Loader=yaml.FullLoader)

    _check_env(env)
    _check_env(env)
    _insert_python(env)
    env_name = _get_env_name(env)

    _create_env(env_file, env_name, package_manager=package_manager)
    return InjectedEnvironment(name=env_name, package_manager=package_manager)


def _create_env(
    env_file: Path,
    env_name: str,
    package_manager: PackageManager = PackageManager.MAMBA,
):
    cmd = [
        package_manager.value,
        "env",
        "create",
        "--name",
        env_name,
        "-f",
        env_file,
    ]
    sp.run(cmd, check=True, stdout=sp.PIPE, stderr=sp.PIPE)


def _insert_python(env: Dict[str, List[str]]):
    # inject python with same version as current environment
    python_package = f"python ={sys.version_info.major}.{sys.version_info.minor}"
    env["dependencies"].append(python_package)


def _get_env_name(env: Dict[str, List[str]]) -> str:
    checksum = hashlib.sha256()
    checksum.update(json.dumps(env).encode("utf-8"))
    env_checksum = checksum.hexdigest()
    return f"conda-inject-{env_checksum}_"


def _get_envs(package_manager: PackageManager) -> Dict[str, str]:
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
