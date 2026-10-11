#!/usr/bin/env bash
# Build a separate raw ext4 GSI artifact using the already checked source/output.
# No source patches, cleanup, kernel build, tablet writes or flashing.
set -eo pipefail

task_project=${1:-/run/media/ilya/SSD512/Y700-LineageOS}
task_project=$(cd -- "$task_project" && pwd -P)
task_source="$task_project/source"
task_output="$task_project/out/gsi-vanilla-ext4"
[[ -f "$task_source/build/envsetup.sh" ]] || {
    printf 'Error: Android source not found: %s\n' "$task_source" >&2; exit 1;
}
[[ -d "$task_output" ]] || {
    printf 'Error: Existing build output not found: %s\n' "$task_output" >&2; exit 1;
}
task_output=$(cd -- "$task_output" && pwd -P)
cd -- "$task_source"
task_alias=$(readlink -f -- out-y700) || task_alias=''
[[ "$task_alias" == "$task_output" ]] || {
    printf 'Error: out-y700 does not point to the checked build output; left unchanged.\n' >&2
    exit 1
}

export OUT_DIR=out-y700
export USE_CCACHE="${USE_CCACHE:-0}"
# Android envsetup expects unset optional variables; do not enable nounset.
source build/envsetup.sh
lunch "${Y700_LUNCH_TARGET:-lineage_arm64_bvN4-bp4a-userdebug}"
task_fs=$(get_build_var BOARD_SYSTEMIMAGE_FILE_SYSTEM_TYPE)
[[ "$task_fs" == ext4 ]] || {
    printf 'Error: Expected the existing ext4 product, got filesystem %s.\n' "$task_fs" >&2
    exit 1
}
task_stamp=$(date -u +%Y%m%d-%H%M%S)
mkdir -p -- "$task_project/logs"
task_log="$task_project/logs/native-systemimage-$task_stamp-$$.log"
m -j"${Y700_BUILD_JOBS:-4}" systemimage simg2img 2>&1 | tee "$task_log"

task_product_out=$(get_build_var PRODUCT_OUT)
task_host_out=$(get_build_var HOST_OUT)
task_image="$task_product_out/system.img"
[[ -s "$task_image" ]] || {
    printf 'Error: Built system.img is missing: %s\n' "$task_image" >&2; exit 1;
}
task_artifact="$task_project/out/artifacts/lineage-23.2-bypass-native-ext4-$task_stamp-$$"
mkdir -p -- "$task_project/out/artifacts"
mkdir -- "$task_artifact"
task_magic=$(od -An -N4 -tx1 -- "$task_image" | tr -d ' \n')
if [[ "$task_magic" == 3aff26ed ]]; then
    "$task_host_out/bin/simg2img" "$task_image" "$task_artifact/system.img"
else
    cp --reflink=auto -- "$task_image" "$task_artifact/system.img"
fi
task_ext4_magic=$(od -An -j1080 -N2 -tx1 -- "$task_artifact/system.img" | tr -d ' \n')
[[ "$task_ext4_magic" == 53ef ]] || {
    printf 'Error: Result is not a raw ext4 image; inspect %s.\n' "$task_artifact" >&2
    exit 1
}
(
    cd -- "$task_artifact"
    sha256sum system.img > system.img.sha256
)
printf '\nRaw ext4 GSI: %s/system.img\n' "$task_artifact"
printf 'SHA-256: '
cat -- "$task_artifact/system.img.sha256"
printf 'Build log: %s\n' "$task_log"
