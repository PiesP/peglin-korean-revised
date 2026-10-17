"""Build the public reference stubs and plugin for hosted checks."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

STUB_PROJECTS = ("UnityEngine.CoreModule", "UnityEngine", "Assembly-CSharp", "Newtonsoft.Json")
BUILT_PROJECTS = ("UnityEngine", "Assembly-CSharp", "Newtonsoft.Json")
ASSEMBLIES = ("UnityEngine", "UnityEngine.CoreModule", "Assembly-CSharp", "Newtonsoft.Json")
TARGETS = """<Project>
  <Target Name="ExcludeGameNetstandardReferenceForPublicStubs" BeforeTargets="ResolveAssemblyReferences">
    <ItemGroup>
      <Reference Remove="netstandard" />
    </ItemGroup>
  </Target>
</Project>
"""


class BuildInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum


def interrupt_build(signum: int, _frame: object) -> None:
    raise BuildInterrupted(signum)


def run_dotnet(arguments: list[str]) -> int:
    try:
        returncode = subprocess.run(["dotnet", *arguments], check=False).returncode
        return returncode if returncode >= 0 else 128 - returncode
    except OSError as exc:
        print(f"Could not start dotnet: {exc}", file=sys.stderr)
        return 1


def build_stubs(reference_dir: Path) -> int:
    for project in STUB_PROJECTS:
        lockfile = Path(f".github/codeql-reference-stubs/{project}/packages.lock.json")
        if not lockfile.is_file():
            print(f"Missing public reference lockfile: {lockfile}", file=sys.stderr)
            return 1

    for command in ("restore", "build"):
        for project in BUILT_PROJECTS:
            project_path = f".github/codeql-reference-stubs/{project}/{project}.csproj"
            arguments = (
                ["--locked-mode", "--configfile", "plugin/NuGet.Config", "--nologo"]
                if command == "restore"
                else [
                    "--no-restore",
                    "--configuration",
                    "Release",
                    "--verbosity",
                    "minimal",
                    "--nologo",
                ]
            )
            status = run_dotnet([command, project_path, *arguments])
            if status:
                return status

    sources = [
        Path(f".github/codeql-reference-stubs/{project}/bin/Release/net46/{assembly}.dll")
        for project, assembly in (
            ("UnityEngine", "UnityEngine"),
            ("UnityEngine", "UnityEngine.CoreModule"),
            ("Assembly-CSharp", "Assembly-CSharp"),
            ("Newtonsoft.Json", "Newtonsoft.Json"),
        )
    ]
    try:
        reference_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        reference_dir.chmod(0o700)
        for source in sources:
            shutil.copy2(source, reference_dir / source.name)
    except OSError as exc:
        print(f"Could not publish public reference assemblies: {exc}", file=sys.stderr)
        return 1
    return 0


def build_plugin(reference_dir: Path) -> int:
    if not Path("plugin/packages.lock.json").is_file():
        print("Missing plugin lockfile: plugin/packages.lock.json", file=sys.stderr)
        return 1
    for assembly in ASSEMBLIES:
        if not (reference_dir / f"{assembly}.dll").is_file():
            print(f"Missing public reference assembly: {assembly}.dll", file=sys.stderr)
            return 1

    project = "plugin/PeglinKoreanRevised.csproj"
    managed_dir = f"-p:PeglinManagedDir={reference_dir}"
    status = run_dotnet(
        [
            "restore",
            project,
            "--locked-mode",
            "--configfile",
            "plugin/NuGet.Config",
            "--nologo",
            managed_dir,
        ]
    )
    if status:
        return status

    temporary_dir = os.environ.get("RUNNER_TEMP") or os.environ.get("TMPDIR") or "/tmp"
    targets: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="peglin-public-stubs.",
            suffix=".targets",
            dir=temporary_dir,
            delete=False,
        ) as targets_file:
            targets = Path(targets_file.name)
            targets_file.write(TARGETS)
        status = run_dotnet(
            [
                "build",
                project,
                "--no-restore",
                "--configuration",
                "Release",
                "--verbosity",
                "minimal",
                "--nologo",
                managed_dir,
                f"-p:CustomAfterMicrosoftCommonTargets={targets}",
                "-p:ContinuousIntegrationBuild=true",
            ]
        )
    except OSError as exc:
        print(f"Could not create public-stub targets: {exc}", file=sys.stderr)
        status = 1
    finally:
        if targets is not None:
            try:
                targets.unlink(missing_ok=True)
            except OSError as exc:
                print(f"Could not remove public-stub targets: {exc}", file=sys.stderr)
                if not status:
                    status = 1
    return status


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: build_public_stub_plugin.py <stubs|plugin> <reference-directory>",
            file=sys.stderr,
        )
        return 2
    stage, reference_dir = argv
    if not reference_dir:
        print("Expected a reference assembly directory", file=sys.stderr)
        return 2
    if stage not in ("stubs", "plugin"):
        print(f"Unknown build stage: {stage}", file=sys.stderr)
        return 2
    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_build)
    try:
        if stage == "stubs":
            return build_stubs(Path(reference_dir))
        return build_plugin(Path(reference_dir))
    except BuildInterrupted as exc:
        print(f"Public-stub build interrupted by signal {exc.signum}", file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        print("Public-stub build interrupted by signal 2", file=sys.stderr)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
