import hashlib
import json
import os
import re
import sys
from enum import Enum
import subprocess as sp
import tempfile

import yaml

package_spec_pattern = re.compile("(?P<package>[^=><\s]+)(\s*)(?P<constraint>.+)?")


class PackageManager(Enum):
    """Enum of supported package managers."""
    MAMBA = "mamba"
    CONDA = "conda"


def inject_packages(channels: list[str], packages: list[str], package_manager: PackageManager = PackageManager.MAMBA):
    """Inject conda packages into the current environment.

    Args:
        channels: List of channels to search for packages.
        packages: List of packages to install.
    """
    env = {
        "channels": channels,
        "dependencies": packages,
    }

    inject_env(env, package_manager)


def inject_env(env: dict[str, list], package_manager: PackageManager = PackageManager.MAMBA):
    """Inject conda packages into the current environment.

    Args:
        env: Environment to inject.
    """
    _check_env(env)

    # inject python with same version as current environment
    python_package = f"python ={sys.version_info.major}.{sys.version_info.minor}"
    env["dependencies"].append(python_package)

    checksum = hashlib.sha256()
    checksum.update(yaml.dumps(env).encode("utf-8"))
    env_checksum = checksum.hexdigest()
    env_name = f"conda-inject-{env_checksum}"

    with tempfile.NamedTemporaryFile(suffix=".conda.yaml") as tmp:
        yaml.dump(env, tmp)
        tmp.flush()
        cmd = [package_manager.value, "env", "create", "-y", "--name", env_name, "-f", tmp.name]
        sp.run(cmd, check=True)

    conda_prefix = os.environ['CONDA_PREFIX']
    sys.path.append(
        f"{conda_prefix}/envs/{env_name}/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )


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