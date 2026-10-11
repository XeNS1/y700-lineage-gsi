# LineageOS 23.2 GSI for Lenovo Legion Y700 Gen 3 (TB321FU)

Unofficial, experimental Android 16 GSI, maintained by [XeNS1](https://github.com/XeNS1).
This repository contains the source changes and a build recipe. Upstream Android
projects are downloaded from their original repositories at pinned revisions.

## Tested configuration

- Lenovo Legion Y700 Gen 3, model **TB321FU**, platform **pineapple**.
- CN stock **ZUX 1.1.10.138**, vendor build
  `TB321FU_CN_OPEN_USER_Q00011.0_V_ZUI_17.0.10.138_ST_250626`.
- Existing stock kernel `6.1.112-android14-11-gd03cb1d7abcd-ab12592111` and vendor.
- LineageOS 23.2 / Android 16, Vanilla, ARM64 A/B GSI, raw ext4 system image.
- DSU boot testing with SELinux **Enforcing**.

The maintainer reports successful boot, camera, flashlight, audio, light games,
native bypass charging and the orientation fix. Other generations, stock versions
and installation methods have not been established by these tests.

## Features

- Native bypass charging switch under Settings > Battery, off by default.
- Russian label: **Обходная зарядка (Экспериментально)**; English translation included.
- Quick Settings tile uses the supplied icon, reflects the service's actual state,
  and is appended to the end of the active tile list when added automatically.
- The native controller uses the tested stock battery sysfs interface. It checks
  charging readback and battery telemetry, with a separate watchdog for recovery.
- TB321FU-specific orientation default respects landscape-only applications.
  Explicit saved orientation overrides remain effective; tablet configuration is retained.

Kernel sources and stock vendor binaries are not built or shipped in this repository.

## Repository layout

| Path | Purpose |
| --- | --- |
| `manifests/base.xml` | Original upstream revision lock, with portable public remote URLs |
| `patches/` | Complete per-project changes relative to that lock, including local commits |
| `payload/` | New source files and required generated product makefiles |
| `export-index.json` | Patch hashes, payload hashes and expected restored file states |
| `scripts/restore-source.py` | Preflight and restore the source delta onto the locked baseline |
| `scripts/native/` | Native controller build checks and stock policy compatibility checker |
| `scripts/` | Source sync, TrebleApp preparation and system image build |
| `export-summary.json` | Export counts and verification scope |

The export is a snapshot of the maintainer's working source. Uncommitted changes
and locally committed GSI preparation changes are both included. The revision lock
uses the **original published upstream commits**, not hashes of private local commits.

The existing firmware was reported working by the maintainer. A complete clean
rebuild of this exported repository has not yet been independently verified.
Release-specific image hashes and download links belong in the release notes.

## Build

Use Linux x86_64, a case-sensitive filesystem, and a work path without spaces.
The maintainer used CachyOS, 16 GiB RAM plus substantial swap. Initial compilation
took about 11.5 hours. Reserve sufficient space for both sources and output; the
earlier preparation script requires at least 150 GiB free before a first build.

Typical Arch/CachyOS dependencies:

```bash
sudo pacman -S --needed base-devel git git-lfs repo python zip unzip \
  bc bison flex gperf cpio rsync libxml2 libxslt libxcrypt-compat \
  ncurses openssl zlib lz4 inetutils jdk17-openjdk
```

Clone this small recipe repository, then use a **new** work directory:

```bash
git clone https://github.com/XeNS1/y700-lineage-gsi.git
cd y700-lineage-gsi
git lfs install

bash scripts/sync-sources.sh /path/to/Y700-LineageOS
python3 scripts/prepare-treble-app.py /path/to/Y700-LineageOS
Y700_BUILD_JOBS=2 bash scripts/build-systemimage.sh /path/to/Y700-LineageOS
```

`sync-sources.sh` downloads the expanded locked manifest and restores all patches
and new files. It refuses to reuse an existing source directory. By default it pins
the manifest repository to the commit of this recipe checkout. Keep that checkout
clean, or set `Y700_RECIPE_REF` to the published tag or commit you intend to build.

TrebleApp is rebuilt from source using the bundled SDK/checksum preparation code.
Its APK, Gradle cache and SDK are not part of this Git repository. The original
`y700-build-gsi.py` is included for its reviewed preparation helpers and provenance;
do not run its full patch installer after `restore-source.py`.

The Android build uses `OUT_DIR=out-y700` pointing to the separate output directory.
This avoids the `platform_testing` absolute-output-path error encountered earlier.
The wrapper requires `TARGET_NO_KERNEL=true` and an ext4 system image before building.
The final raw image and SHA-256 are saved under the work directory's `out/artifacts/`.

Optional native module/controller checks:

```bash
bash scripts/native/build-check.sh /path/to/Y700-LineageOS
```

That check also links the new policy with stock vendor policy using a connected
rooted TB321FU. The compatibility checker reads policy; it does not switch SELinux
to Permissive. Host controller checks cover 22 charging/watchdog cases.

## Testing and installation

Published images are experimental GSIs. The established test path is DSU on the
CN stock configuration above. DSU boot on the previous ColorOS port failed for both
this project and a previously working Lunaris GSI; stock restoration resolved it.

This repository does not contain a device OTA package or a complete stock restoration
archive. Boot/init_boot/vendor images are not included. Permanent installation and
support for other stock bases require separate validation and instructions.

## Releases

Keep `system.img` outside Git history. Distribute compressed images through GitHub
Releases, with SHA-256 checksums and the exact source tag. Each uploaded release
asset must be smaller than 2 GiB; larger compressed images need chunks or an
external download host. Record any observed issues in the release notes.

## License and credits

New integration and export scripts are supplied under Apache-2.0, see `LICENSE`.
Existing upstream files and patches retain their original licenses and copyright
headers. The top-level license does not relicense all downloaded Android projects.

Thanks to [LineageOS](https://github.com/LineageOS),
[AOSP](https://android.googlesource.com/),
[TrebleDroid](https://github.com/TrebleDroid),
[PHH](https://github.com/phhusson), and
[MisterZtr's GSI project](https://github.com/MisterZtr/LineageOS_gsi).
This project is not an official LineageOS release or a Lenovo product.
