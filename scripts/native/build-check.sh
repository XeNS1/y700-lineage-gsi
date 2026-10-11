#!/usr/bin/env bash
set -euo pipefail
task_project=${1:-/run/media/ilya/SSD512/Y700-LineageOS}
task_source="$task_project/source"
if [[ -f "$task_project/build/envsetup.sh" ]]; then task_source="$task_project"; task_project=$(dirname "$task_project"); fi
task_package=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
task_project=$(cd -- "$task_project" && pwd -P)
cd -- "$task_source"
# Soong rejects the absolute generated data path in platform_testing. Keep the
# relative alias used by the successful GSI build, with the same physical output.
task_output="$task_project/out/gsi-vanilla-ext4"
mkdir -p -- "$task_output"
task_output=$(cd -- "$task_output" && pwd -P)
if [[ -e out-y700 || -L out-y700 ]]; then
    task_link_target=$(readlink -f -- out-y700) || task_link_target=''
    if [[ "$task_link_target" != "$task_output" ]]; then
        printf 'Error: %s/out-y700 does not point to %s; it was left unchanged.\n' "$PWD" "$task_output" >&2
        exit 1
    fi
else
    ln -s -- "$task_output" out-y700
fi
export OUT_DIR=out-y700
export USE_CCACHE="${USE_CCACHE:-0}"
printf 'OUT_DIR=%s -> %s\n' "$OUT_DIR" "$task_output"
# Android's envsetup uses optional variables; do not apply nounset to it.
set +u
source build/envsetup.sh
lunch "${Y700_LUNCH_TARGET:-lineage_arm64_bvN4-bp4a-userdebug}"
task_ignore_neverallows=$(get_build_var SELINUX_IGNORE_NEVERALLOWS)
printf 'Existing product SELINUX_IGNORE_NEVERALLOWS=%s (this package does not change it).\n' "${task_ignore_neverallows:-false}"
task_host_out=$(get_build_var HOST_OUT)
if [[ -x "$task_host_out/bin/checkfc" ]]; then
    printf '%s\n' 'Checking file-context test samples before rebuilding modules.'
    "$task_host_out/bin/checkfc" -t system/sepolicy/private/file_contexts system/sepolicy/contexts/file_contexts_test_data
fi
task_targets=(services Settings SystemUI y700_bypassd y700_bypass_core_test selinux_policy)
if [[ $(get_build_var PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT) == true ]]; then
    task_targets+=(system_ext_userdebug_plat_sepolicy.cil)
fi
m -j"${Y700_BUILD_JOBS:-4}" "${task_targets[@]}"
task_product_out=$(get_build_var PRODUCT_OUT)
task_host_out=$(get_build_var HOST_OUT)
set -u
task_test="$task_host_out/nativetest64/y700_bypass_core_test/y700_bypass_core_test"
if [[ ! -x "$task_test" ]]; then task_test="$task_host_out/nativetest/y700_bypass_core_test/y700_bypass_core_test"; fi
"$task_test"
task_verify_args=("$task_project" --product-out "$task_product_out" --secilc "$task_host_out/bin/secilc")
if [[ -n ${Y700_ADB_SERIAL:-} ]]; then task_verify_args+=(--serial "$Y700_ADB_SERIAL"); fi
python3 "$task_package/verify-vendor-policy.py" "${task_verify_args[@]}"
printf '%s\n' 'WindowManager (services), Settings, SystemUI, native modules, controller tests and stock vendor policy link passed.'
printf '%s\n' 'Now run the existing systemimage build script with the same OUT_DIR.'
