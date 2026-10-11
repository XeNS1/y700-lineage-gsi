#!/usr/bin/env bash
# Prepare the relative output alias and build the exported system image.
set -eo pipefail
task_work=${1:?Usage: build-systemimage.sh /absolute/path/Y700-LineageOS}
task_work=$(cd -- "$task_work" && pwd -P)
task_recipe=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
task_source="$task_work/source"
mkdir -p -- "$task_work/out/gsi-vanilla-ext4"
cd -- "$task_source"
if [[ -e out-y700 || -L out-y700 ]]; then
  [[ $(readlink -f -- out-y700) == "$task_work/out/gsi-vanilla-ext4" ]] || {
    echo 'Existing out-y700 points elsewhere; preserved.' >&2; exit 1;
  }
else
  ln -s ../out/gsi-vanilla-ext4 out-y700
fi
export OUT_DIR=out-y700
export USE_CCACHE=0
source build/envsetup.sh
lunch lineage_arm64_bvN4-bp4a-userdebug
[[ $(get_build_var TARGET_NO_KERNEL) == true ]] || {
  echo 'This recipe must use TARGET_NO_KERNEL=true.' >&2; exit 1;
}
[[ $(get_build_var BOARD_SYSTEMIMAGE_FILE_SYSTEM_TYPE) == ext4 ]] || {
  echo 'This recipe must build an ext4 system image.' >&2; exit 1;
}
export Y700_BUILD_JOBS=${Y700_BUILD_JOBS:-2}
bash "$task_recipe/scripts/y700-build-native-systemimage.sh" "$task_work"
