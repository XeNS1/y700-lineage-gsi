#!/usr/bin/env bash
# Sync a fresh source tree using the published upstream lock.
set -euo pipefail
task_work=${1:?Usage: sync-sources.sh /absolute/path/Y700-LineageOS}
task_work=$(realpath -m -- "$task_work")
[[ "$task_work" != *[[:space:]]* ]] || { echo 'Use a path without whitespace.' >&2; exit 1; }
[[ ! -e "$task_work/source" ]] || { echo 'Use a fresh work directory; existing source preserved.' >&2; exit 1; }
task_recipe=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
task_ref=${Y700_RECIPE_REF:-$(git -C "$task_recipe" rev-parse HEAD)}
mkdir -p -- "$task_work/source" "$task_work/metadata" "$task_work/tmp" "$task_work/logs"
cd -- "$task_work/source"
repo init -u https://github.com/XeNS1/y700-lineage-gsi.git \
  -b "$task_ref" --manifest-upstream-branch refs/heads/main -m manifests/base.xml \
  --depth=1 --git-lfs --no-clone-bundle --no-tags
repo sync -c -j"${Y700_SYNC_JOBS:-4}" --no-manifest-update \
  --no-clone-bundle --no-tags --fail-fast --retry-fetches=3
cp -- "$task_recipe/manifests/base.xml" "$task_work/metadata/source-lock.xml"
python3 "$task_recipe/scripts/restore-source.py" "$task_work/source"
