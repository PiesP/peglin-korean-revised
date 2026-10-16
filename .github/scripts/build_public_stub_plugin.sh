#!/usr/bin/env bash
set -euo pipefail

stage="${1:?Expected stubs or plugin stage}"
reference_dir="${2:?Expected a reference assembly directory}"

if [[ "$stage" == stubs ]]; then
  for project in UnityEngine.CoreModule UnityEngine Assembly-CSharp Newtonsoft.Json; do
    lockfile=".github/codeql-reference-stubs/$project/packages.lock.json"
    if [[ ! -f "$lockfile" ]]; then
      echo "Missing public reference lockfile: $lockfile" >&2
      exit 1
    fi
  done

  for project in UnityEngine Assembly-CSharp Newtonsoft.Json; do
    dotnet restore ".github/codeql-reference-stubs/$project/$project.csproj" \
      --locked-mode --configfile plugin/NuGet.Config --nologo
  done
  for project in UnityEngine Assembly-CSharp Newtonsoft.Json; do
    dotnet build ".github/codeql-reference-stubs/$project/$project.csproj" \
      --no-restore --configuration Release --verbosity minimal --nologo
  done

  install -d -m 0700 "$reference_dir"
  cp .github/codeql-reference-stubs/UnityEngine/bin/Release/net46/UnityEngine.dll \
    .github/codeql-reference-stubs/UnityEngine/bin/Release/net46/UnityEngine.CoreModule.dll \
    .github/codeql-reference-stubs/Assembly-CSharp/bin/Release/net46/Assembly-CSharp.dll \
    .github/codeql-reference-stubs/Newtonsoft.Json/bin/Release/net46/Newtonsoft.Json.dll \
    "$reference_dir/"
elif [[ "$stage" == plugin ]]; then
  if [[ ! -f plugin/packages.lock.json ]]; then
    echo "Missing plugin lockfile: plugin/packages.lock.json" >&2
    exit 1
  fi
  for assembly in Assembly-CSharp UnityEngine UnityEngine.CoreModule Newtonsoft.Json; do
    if [[ ! -f "$reference_dir/$assembly.dll" ]]; then
      echo "Missing public reference assembly: $assembly.dll" >&2
      exit 1
    fi
  done

  dotnet restore plugin/PeglinKoreanRevised.csproj \
    --locked-mode --configfile plugin/NuGet.Config --nologo \
    -p:PeglinManagedDir="$reference_dir"

  targets="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/peglin-public-stubs.XXXXXX.targets")"
  trap 'rm -f "$targets"' EXIT
  cat > "$targets" <<'XML'
<Project>
  <Target Name="ExcludeGameNetstandardReferenceForPublicStubs" BeforeTargets="ResolveAssemblyReferences">
    <ItemGroup>
      <Reference Remove="netstandard" />
    </ItemGroup>
  </Target>
</Project>
XML
  dotnet build plugin/PeglinKoreanRevised.csproj \
    --no-restore --configuration Release --verbosity minimal --nologo \
    -p:PeglinManagedDir="$reference_dir" \
    -p:CustomAfterMicrosoftCommonTargets="$targets" \
    -p:ContinuousIntegrationBuild=true
else
  echo "Unknown build stage: $stage" >&2
  exit 2
fi
