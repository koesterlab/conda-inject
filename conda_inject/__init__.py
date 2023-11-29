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
from typing import Dict, List, Optional, Set

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
            stderr=sp.STDOUT,
        )
        self.deactivate()

    def deactivate(self):
        injection = self._get_syspath_injection()
        try:
            sys.path.remove(injection)
        except ValueError:
            # nothing to remove
            pass
        os.environ["PATH"] = os.environ["PATH"].replace(self._get_path_injection(), "")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.deactivate()

    def _inject_path(self):
        # manipulate python path
        sys.path.append(self._get_syspath_injection())
        # manipulate PATH
        os.environ["PATH"] = f"{os.environ['PATH']}{self._get_path_injection()}"

    def _get_path_injection(self):
        return f":{self.env.path}/bin"

    def _get_syspath_injection(self):
        return (
            f"{self.env.path}/lib/"
            f"python{sys.version_info.major}.{sys.version_info.minor}/"
            "site-packages"
        )


def inject_packages(
    channels: List[str],
    packages: List[str],
    with_constraints: Optional[List[str]] = None,
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

    return inject_env(
        env, package_manager=package_manager, with_constraints=with_constraints
    )


def inject_env(
    env: Dict[str, List[str]],
    with_constraints: Optional[List[str]] = None,
    package_manager: PackageManager = PackageManager.MAMBA,
) -> InjectedEnvironment:
    """Inject conda packages into the current environment.

    Args:
        env: Environment to inject, given as dict with the keys `channels` and
             `dependencies`. The expected values are the same as for conda
             `environment.yml` files.
    """
    invalid_packages = _get_invalid_packages(with_constraints)
    _check_env(env, invalid_packages=invalid_packages)
    _insert_constraints(env, with_constraints)
    env_name = _get_env_name(env)

    envs = _get_envs(package_manager)

    if env_name not in envs:
        with tempfile.NamedTemporaryFile(suffix=".conda.yaml", mode="w") as tmp:
            yaml.dump(env, tmp)
            tmp.flush()
            _create_env(Path(tmp.name), env_name, package_manager=package_manager)

    return InjectedEnvironment(name=env_name, package_manager=package_manager)


def inject_env_file(
    env_file: Path,
    with_constraints: Optional[List[str]] = None,
    package_manager: PackageManager = PackageManager.MAMBA,
):
    with open(env_file) as f:
        env = yaml.load(f, Loader=yaml.FullLoader)
    return inject_env(
        env, package_manager=package_manager, with_constraints=with_constraints
    )


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
    sp.run(cmd, check=True, stdout=sp.PIPE, stderr=sp.STDOUT)


def _insert_constraints(env: Dict[str, List[str]], constraints: Optional[List[str]]):
    # inject python with same version as current environment
    python_package = f"python =={sys.version_info.major}.{sys.version_info.minor}"
    env["dependencies"].append(python_package)
    # add other constraints
    if constraints:
        env["dependencies"].extend(constraints)


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
            stderr=sp.STDOUT,
        ).stdout.decode()
    )["envs"]
    return {env.name: env for env in map(Environment, envs)}


def _check_env(
    env: dict[str, list], invalid_packages: Optional[Set[str]] = None
) -> bool:
    """Check if the given environment is valid."""
    if "channels" not in env:
        raise ValueError("Missing 'channels' in environment.")
    if "dependencies" not in env:
        raise ValueError("Missing 'dependencies' in environment.")
    _check_packages(env["dependencies"], invalid_packages=invalid_packages)


def _check_packages(packages, invalid_packages: Optional[Set[str]] = None):
    """Check if the given package specs are valid."""
    invalid_packages = {"python"} if invalid_packages is None else invalid_packages

    for package_spec in packages:
        m = package_spec_pattern.match(package_spec)
        if m:
            package_name = m.group("package")
            if package_name in invalid_packages:
                raise ValueError(
                    f"The list of packages contains {package_name}. "
                    "This is not allowed as conda-inject automatically "
                    f"chooses a {package_name} version matching to the current "
                    "environment."
                )
        else:
            raise ValueError(
                "Invalid package spec. Must be of the form "
                "'mypackage=1.0.0' or 'mypackage>=1.0.0'"
            )


def _get_invalid_packages(constraints: Optional[List[str]] = None) -> Set[str]:
    invalid_packages = {"python"}
    if constraints is not None:
        _check_packages(constraints, invalid_packages=invalid_packages)
    if constraints:
        for constraint in constraints:
            m = package_spec_pattern.match(constraint)
            if m:
                invalid_packages.add(m.group("package"))
    return invalid_packages
