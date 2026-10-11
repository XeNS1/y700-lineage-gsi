#!/usr/bin/env python3
"""First LineageOS 23.2 Vanilla GSI build for the existing Y700 workspace.

Usage:
  python3 y700-build-gsi.py [--check-only | --prepare-only] /run/media/ilya/SSD512
  Y700_BUILD_JOBS=1 python3 y700-build-gsi.py /run/media/ilya/SSD512

No device access. No repo sync, kernel compilation, firmware installation,
source reset or git clean. All upstream patches must pass before installation.
The output is an experimental generic baseline, not a finished TB321FU ROM.

Recipe:
  https://github.com/MisterZtr/LineageOS_gsi/tree/7bf212f449d1aa253ebc97b1ab3c4924be88effa
  https://dl.google.com/android/repository/repository2-3.xml
  https://developer.android.com/build/releases/agp-7-4-0-release-notes
  https://services.gradle.org/distributions/gradle-7.5-all.zip.sha256
"""

import argparse
import contextlib
import datetime
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

GSI_REV = "7bf212f449d1aa253ebc97b1ab3c4924be88effa"
DEVICE_REV = "91031960bf9f5ccf4e0af412db12138b7e26bd5b"
APP_REV = "96acf04e74d42a08cc841688686ad3c5d8bd5790"
TARGET = "lineage_arm64_bvN4-bp4a-userdebug"
GOODIX_PATCH_SHA = "929c57e66ef499e50a0838626200c510783d674036032f35b32570d0e625f12d"
GRADLE_SHA = "97a52d145762adc241bad7fd18289bf7f6801e08ece6badf80402fe2b9f250b1"
SDK_PACKAGES = [
    ("platform-33-ext3_r03.zip", 67334237,
     "b32b10f787867987f03ae8e101d217e053a9065b7136379fb353b388379aed1d",
     "android-13", "platforms/android-33", "android.jar"),
    ("build-tools_r30.0.3-linux.zip", 53134793,
     "24593500aa95d2f99fb4f10658aae7e65cb519be6cd33fa164f15f27f3c4a2d6",
     "android-11", "build-tools/30.0.3", "aapt2"),
]
PACMAN = ("sudo pacman -Syu --needed base-devel git git-lfs repo python "
          "zip unzip bc bison flex gperf cpio rsync libxml2 libxslt "
          "libxcrypt-compat ncurses openssl zlib lz4 inetutils jdk17-openjdk")
LOG = None


class Stop(RuntimeError):
    pass


def say(message):
    print(message, flush=True)
    if LOG:
        LOG.write(str(message) + "\n")
        LOG.flush()


def digest(path):
    with Path(path).open("rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value:
        raise Stop("Небезопасный относительный путь: " + value)
    return p


def run(argv, cwd=None, env=None, data=None, check=True):
    result = subprocess.run(
        [str(a) for a in argv], cwd=cwd, env=env, input=data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = (result.stdout + result.stderr).decode("utf-8", "replace")
        raise Stop(f"Команда завершилась с кодом {result.returncode}: "
                   + " ".join(str(a) for a in argv) + "\n" + detail)
    return result


def git(repo, *args, env=None, data=None, check=True):
    # Local command-scoped settings; user's global Git config is untouched.
    return run([
        "git", "-C", repo, "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false", "-c", "user.name=Y700 GSI Builder",
        "-c", "user.email=y700-build@localhost", *args,
    ], env=env, data=data, check=check)


def git_text(repo, *args, env=None):
    return git(repo, *args, env=env).stdout.decode().strip()


def streamed(argv, cwd, env):
    say("\nЗапуск: " + " ".join(str(a) for a in argv))
    with subprocess.Popen(
        [str(a) for a in argv], cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as proc:
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                if LOG:
                    LOG.write(line)
                    LOG.flush()
            code = proc.wait()
        except BaseException:
            proc.terminate()
            proc.wait()
            raise
    if code:
        raise Stop(f"Сборка остановлена, код {code}. Смотри первую ошибку в логе.")


def locked(path, stack):
    handle = stack.enter_context(Path(path).open("a"))
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise Stop("Другой процесс использует рабочую папку: " + str(path))


def host_check(work, building):
    tools = ["git", "repo", "bash"]
    if building:
        tools += ["make", "gcc", "g++", "zip", "unzip", "bc", "bison",
                  "flex", "gperf", "cpio", "rsync", "xmllint", "lz4"]
    missing = [t for t in tools if not shutil.which(t)]
    java = Path(os.environ.get("Y700_JAVA17", "/usr/lib/jvm/java-17-openjdk"))
    if building:
        if not (java / "bin/javac").is_file():
            missing.append("JDK 17 (/usr/lib/jvm/java-17-openjdk)")
        else:
            result = run([java / "bin/javac", "-version"])
            version = (result.stdout + result.stderr).decode()
            if not re.search(r"\b17\.", version):
                missing.append("JDK 17 (Y700_JAVA17 указывает на другую версию)")
    if missing:
        raise Stop("Не хватает: " + ", ".join(missing) + "\n" + PACMAN)
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:")):
            key, value, *_ = line.split()
            memory[key[:-1]] = int(value) * 1024
    space = shutil.disk_usage(work).free
    say(f"Свободно на диске: {space / 2**30:.1f} GiB")
    say(f"RAM: {memory.get('MemTotal', 0) / 2**30:.1f} GiB; "
        f"swap: {memory.get('SwapTotal', 0) / 2**30:.1f} GiB")
    if building:
        first_build = not (work / "metadata/gsi-build-started.json").is_file()
        required = 150 * 2**30 if first_build else 20 * 2**30
        if space < required:
            raise Stop(f"Нужно хотя бы {required / 2**30:.0f} GiB свободного места. "
                       "Это запас для сборки, не измеренный размер результата.")
        if memory.get("MemTotal", 0) < 32 * 2**30:
            say("На этом объёме RAM Soong может активно использовать swap. "
                "Две задачи не ограничивают память отдельного процесса.")
    return java, memory


def collect_recipe(src, lock_path):
    root = ET.parse(lock_path).getroot()
    revisions = {}
    for project in root.findall("project"):
        path = project.get("path", project.get("name"))
        safe_relative(path)
        revision = project.get("revision", "")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise Stop("source-lock.xml содержит незакреплённую ревизию: " + path)
        revisions[path] = revision
    for path, expected in {
        "LineageOS_gsi": GSI_REV, "device/phh/treble": DEVICE_REV,
        "treble_app": APP_REV,
    }.items():
        if revisions.get(path) != expected:
            raise Stop("Другая версия " + path + " в source-lock.xml.")
    if git_text(src / "LineageOS_gsi", "rev-parse", "HEAD") != GSI_REV:
        raise Stop("Набор GSI-патчей переключён на другую версию.")
    if git_text(src / "LineageOS_gsi", "status", "--porcelain"):
        raise Stop("Есть изменения в LineageOS_gsi; они сохранены.")

    projects = {}
    patches_root = src / "LineageOS_gsi/patches"
    aliases = {"build": "build/make", "testing": "platform_testing",
               "vendor/hardware/overlay": "vendor/hardware_overlay",
               "treble/app": "treble_app", "vendor/partner/gms": "vendor/partner_gms"}
    for stage in ["trebledroid", "trebledroid-staging", "personal"]:
        stage_root = patches_root / stage
        if not stage_root.is_dir():
            raise Stop("Отсутствует обязательная группа патчей: " + stage)
        for directory in sorted(stage_root.iterdir()):
            if not directory.is_dir():
                raise Stop("Неожиданный файл среди каталогов патчей: " + str(directory))
            name = directory.name.replace("_", "/").replace("platform/", "")
            name = aliases.get(name, name)
            safe_relative(name)
            # kernel/configs is Android VINTF requirements data, not Linux sources.
            if name.startswith("kernel/") and name != "kernel/configs":
                raise Stop("Рецепт затрагивает исходники ядра: " + name)
            if name not in revisions or not (src / name).is_dir():
                raise Stop("Не скачан проект для патчей: " + name)
            patches = sorted(directory.glob("*.patch"))
            if not patches:
                raise Stop("Пустая группа патчей: " + str(directory))
            entry = projects.setdefault(name, {"base": revisions[name], "patches": []})
            for patch in patches:
                entry["patches"].append({
                    "path": str(patch.relative_to(src)), "sha256": digest(patch),
                })
    payload = {"version": 1, "target": TARGET, "source_lock_sha256": digest(lock_path),
               "projects": projects, "local_app_build_fix": 1, "gradle_sha256": GRADLE_SHA}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return projects, hashlib.sha256(encoded).hexdigest()


def verify_sources(src, projects, state=None):
    entries = state["projects"] if state else {}
    for name, spec in projects.items():
        repo = src / name
        expected = entries.get(name)
        dirty = git_text(repo, "status", "--porcelain", "--untracked-files=normal")
        if dirty and not (expected and pending_index_is_ours(repo, expected)):
            raise Stop("Есть изменения в " + name + "; они сохранены:\n" + dirty)
        head = git_text(repo, "rev-parse", "HEAD")
        if head == spec["base"]:
            continue
        if not expected:
            raise Stop("HEAD отличается от source-lock.xml: " + name)
        parent = git_text(repo, "rev-parse", "HEAD^")
        tree = git_text(repo, "rev-parse", "HEAD^{tree}")
        message = git_text(repo, "log", "-1", "--format=%B")
        if (parent != spec["base"] or tree != expected["tree"]
                or state["marker"] not in message):
            raise Stop("После подготовки изменён проект " + name + ". Изменения сохранены.")


def pending_index_is_ours(repo, entry):
    """Resume a stop between applying the exact verified diff and committing."""
    return (
        git_text(repo, "rev-parse", "HEAD") == entry["base"]
        and git_text(repo, "write-tree") == entry["tree"]
        and git(repo, "diff", "--quiet", "--no-ext-diff", check=False).returncode == 0
        and not git_text(repo, "ls-files", "--others", "--exclude-standard")
    )


def local_app_fix(repo, env):
    for filename in ["build.gradle", "gradle/wrapper/gradle-wrapper.properties"]:
        before = git(repo, "show", ":" + filename, env=env).stdout.decode()
        if filename == "build.gradle":
            if before.count("jcenter()") != 2:
                raise Stop("Неожиданный build.gradle TrebleApp; нельзя заменять репозитории.")
            after = before.replace("jcenter()", "mavenCentral()")
        else:
            if "gradle-7.5-all.zip" not in before or "distributionSha256Sum=" in before:
                raise Stop("Неожиданная конфигурация Gradle wrapper.")
            after = before.rstrip() + "\ndistributionSha256Sum=" + GRADLE_SHA + "\n"
        patch = "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile="a/" + filename, tofile="b/" + filename,
        )).encode()
        git(repo, "apply", "--cached", "--whitespace=nowarn", "-", env=env, data=patch)


def failure_files(repo, patch, env, target):
    """Save public source preimages for repairing the first failed patch."""
    paths = set()
    for line in patch.read_text(errors="replace").splitlines():
        match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", line)
        if match:
            paths.update(match.groups())
    for path in sorted(paths):
        safe_relative(path)
        content = git(repo, "show", ":" + path, env=env, check=False)
        if content.returncode == 0 and len(content.stdout) <= 5 * 1024 * 1024:
            dest = target / "preimages" / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content.stdout)
    shutil.copy2(patch, target / patch.name)


def preflight(src, work, projects, recipe, stamp):
    """All edits go to private indices AND private object databases."""
    cache = work / "metadata/gsi-prepared-v1"
    cache.mkdir(exist_ok=True)
    report_dir = work / "metadata" / ("gsi-preflight-" + stamp)
    report_dir.mkdir()
    shutil.copy2(work / "metadata/source-lock.xml", report_dir / "source-lock.xml")
    entries, conflicts, results = {}, [], []
    with tempfile.TemporaryDirectory(prefix="gsi-preflight-", dir=work / "tmp") as tmp:
        for count, (name, spec) in enumerate(projects.items(), 1):
            say(f"Проверка патчей {count}/{len(projects)}: {name}")
            repo = src / name
            private = Path(tmp) / str(count)
            (private / "objects").mkdir(parents=True)
            object_dir = Path(git_text(repo, "rev-parse", "--git-path", "objects"))
            if not object_dir.is_absolute():
                object_dir = repo / object_dir
            env = os.environ.copy()
            env.update({
                "GIT_INDEX_FILE": str(private / "index"),
                "GIT_OBJECT_DIRECTORY": str(private / "objects"),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(object_dir.resolve()),
            })
            git(repo, "read-tree", spec["base"], env=env)
            failed = False
            for item in spec["patches"]:
                patch = src / item["path"]
                options = ["--cached", "--whitespace=nowarn"]
                # This exact reviewed hunk assumes rw-system.sh ends at the
                # goodix write. The pinned source has more code after it.
                # unidiff-zero only relaxes the EOF constraint for this one
                # checksummed patch; all its supplied context must still match.
                if item["sha256"] == GOODIX_PATCH_SHA:
                    options.append("--unidiff-zero")
                check = git(repo, "apply", *options, "--check", patch,
                            env=env, check=False)
                if check.returncode:
                    reverse = git(repo, "apply", *options, "--reverse", "--check",
                                  patch, env=env, check=False)
                    if reverse.returncode == 0:
                        results.append({"project": name, **item, "status": "already-present"})
                        continue
                    detail = (check.stdout + check.stderr).decode("utf-8", "replace")
                    conflict = {"project": name, **item, "error": detail}
                    conflicts.append(conflict)
                    say("Несовместимый патч: " + item["path"] + "\n" + detail)
                    target = report_dir / "failures" / name
                    target.mkdir(parents=True)
                    failure_files(repo, patch, env, target)
                    results.append({**conflict, "status": "failed"})
                    failed = True
                    break  # Later patches in this project depend on this patch.
                git(repo, "apply", *options, patch, env=env)
                results.append({"project": name, **item, "status": "ok"})
            if failed:
                continue
            if name == "treble_app":
                local_app_fix(repo, env)
            tree = git_text(repo, "write-tree", env=env)
            composite = git(repo, "diff", "--cached", "--no-ext-diff", "--no-textconv",
                            "--binary", "--full-index",
                            spec["base"], "--", env=env).stdout
            dest = cache / (name + ".patch")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(composite)
            entries[name] = {"base": spec["base"], "tree": tree,
                             "diff": str(dest.relative_to(work)),
                             "diff_sha256": digest(dest), "commit": None}
            # Also check the real index/worktree before any source is changed.
            if composite:
                git(repo, "apply", "--index", "--check", "--whitespace=nowarn", "-",
                    data=composite)
    save_json(report_dir / "patch-check.json", {"recipe": recipe, "results": results,
                                               "conflicts": conflicts})
    verify_sources(src, projects)
    if conflicts:
        archive = shutil.make_archive(str(report_dir), "zip", report_dir)
        raise Stop(f"Есть конфликты в {len(conflicts)} проектах. Исходники не изменены.\n"
                   f"Архив для разбора: {archive}")
    state = {"version": 1, "recipe": recipe, "target": TARGET,
             "marker": "Y700-GSI-Recipe: " + recipe, "projects": entries,
             "preflight_report": str(report_dir)}
    save_json(cache / "state.json", state)
    say("Весь набор патчей прошёл предварительную проверку.")
    return state


def install_patches(src, work, state):
    state_path = work / "metadata/gsi-prepared-v1/state.json"
    for name, entry in state["projects"].items():
        repo = src / name
        head = git_text(repo, "rev-parse", "HEAD")
        composite = work / entry["diff"]
        if digest(composite) != entry["diff_sha256"]:
            raise Stop("Изменён сохранённый составной патч: " + str(composite))
        if head == entry["base"] and composite.stat().st_size:
            say("Применение проверенных патчей: " + name)
            if not pending_index_is_ours(repo, entry):
                git(repo, "apply", "--index", "--whitespace=nowarn", composite)
            if git_text(repo, "write-tree") != entry["tree"]:
                raise Stop("Неожиданный результат патчей в " + name)
            message = ("Apply reviewed LineageOS 23.2 GSI patch series\n\n"
                       + state["marker"] + "\nBase: " + entry["base"] + "\n")
            # Commit only the verified index, not any other files.
            git(repo, "commit", "--no-verify", "-F", "-", data=message.encode())
            head = git_text(repo, "rev-parse", "HEAD")
        entry["commit"] = head
        save_json(state_path, state)
    run(["repo", "manifest", "-r", "-o", work / "metadata/gsi-after-patches.xml"], cwd=src)


def download_sdk_archive(work, package):
    name, size, checksum, *_ = package
    path = work / "host/downloads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size == size and digest(path) == checksum:
        return path
    partial = path.with_name(name + ".part")
    say("Загрузка Android SDK: " + name)
    request = urllib.request.Request(
        "https://dl.google.com/android/repository/" + name,
        headers={"User-Agent": "Y700-LineageOS-preparation/1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as f:
        shutil.copyfileobj(response, f, 1024 * 1024)
    if partial.stat().st_size != size or digest(partial) != checksum:
        raise Stop("Размер или SHA-256 не совпал для " + name)
    partial.replace(path)
    return path


def unpack_sdk(archive, destination, root_name):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise Stop("Незавершённая или чужая папка SDK сохранена: " + str(destination))
    with tempfile.TemporaryDirectory(prefix=".sdk-unpack-", dir=destination.parent) as tmp:
        target = Path(tmp) / "package"
        target.mkdir()
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                original = safe_relative(member.filename.rstrip("/"))
                if original.parts[0] != root_name:
                    raise Stop("Неожиданный корень архива Android SDK.")
                relative = PurePosixPath(*original.parts[1:])
                if not relative.parts:
                    continue
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise Stop("Неожиданный симлинк в архиве Android SDK.")
                dest = target.joinpath(*relative.parts)
                if member.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as source, dest.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    dest.chmod(0o755 if mode & 0o111 else 0o644)
        target.rename(destination)


def prepare_sdk(work, src):
    sdk = work / "host/android-sdk"
    for package in SDK_PACKAGES:
        name, _, checksum, root_name, relative, test_file = package
        dest = sdk / relative
        marker = dest / ".y700-sdk.json"
        if marker.is_file():
            recorded = json.loads(marker.read_text())
            if recorded.get("sha256") != checksum or not (dest / test_file).is_file():
                raise Stop("Изменён пакет SDK: " + str(dest))
            continue
        archive = download_sdk_archive(work, package)
        unpack_sdk(archive, dest, root_name)
        if not (dest / test_file).is_file():
            raise Stop("Не хватает файла SDK " + test_file)
        save_json(marker, {"archive": name, "sha256": checksum})
    # These license hashes are already provided by the pinned upstream app.
    licenses = sdk / "licenses"
    licenses.mkdir(exist_ok=True)
    for source in (src / "treble_app/sdk/licenses").iterdir():
        if source.is_file():
            dest = licenses / source.name
            if dest.exists() and dest.read_bytes() != source.read_bytes():
                raise Stop("Файл лицензии SDK уже изменён: " + str(dest))
            shutil.copy2(source, dest)
    return sdk


def build_app(src, work, java, sdk):
    app = src / "treble_app"
    local = app / "local.properties"
    if local.exists():
        raise Stop("В treble_app есть local.properties. Сохрани/перемести его отдельно, "
                   "чтобы не использовать SDK из другого проекта.")
    env = os.environ.copy()
    env.update({"JAVA_HOME": str(java), "PATH": str(java / "bin") + ":" + env["PATH"],
                "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk),
                "GRADLE_USER_HOME": str(work / "host/gradle")})
    streamed(["bash", "./gradlew", "--no-daemon", "--max-workers", "1",
              "-Dorg.gradle.jvmargs=-Xmx2048m", "assembleRelease"], app, env)
    unsigned = app / "app/build/outputs/apk/release/app-release-unsigned.apk"
    if not unsigned.is_file():
        raise Stop("TrebleApp не создал ожидаемый APK: " + str(unsigned))
    env["LD_LIBRARY_PATH"] = str(app / "signapk")
    streamed([java / "bin/java", "-jar", "signapk/signapk.jar",
              "keys/platform.x509.pem", "keys/platform.pk8",
              unsigned, "TrebleApp.apk"], app, env)
    output = app / "TrebleApp.apk"
    if not output.is_file():
        raise Stop("Нет подписанного TrebleApp.apk.")
    save_json(work / "metadata/treble-app-build.json",
              {"sha256": digest(output), "jdk": str(java), "sdk": str(sdk)})


BUILD_SHELL = r"""
set -eo pipefail
source build/envsetup.sh
lunch "$Y700_BUILD_TARGET"
no_kernel="$(get_build_var TARGET_NO_KERNEL)"
filesystem="$(get_build_var BOARD_SYSTEMIMAGE_FILE_SYSTEM_TYPE)"
if [ "$no_kernel" != true ]; then
    echo "Ошибка: выбранная цель может собирать ядро." >&2
    exit 1
fi
if [ "$filesystem" != ext4 ]; then
    echo "Ошибка: вместо ожидаемого ext4 выбран другой формат." >&2
    exit 1
fi
product_out="$(get_build_var PRODUCT_OUT)"
printf '%s\n' "$product_out" > "$Y700_PRODUCT_OUT_FILE"
echo "Цель проверена: TARGET_NO_KERNEL=true; system=ext4"
m -j"$Y700_BUILD_JOBS" systemimage
"""


def output_directory_alias(src, output_dir):
    """Use a source-relative OUT_DIR while keeping the existing build files.

    ci_tests/ci_test_package_zip.go skips host paths starting with "out", then
    appends remaining installed paths to STAGING. An absolute OUT_DIR reaches
    validatePathInternal and is rejected. OUT_DIR=../out/... also fails.
    The relative "out-y700" symlink keeps the expected prefix and existing files.
    """
    alias = src / "out-y700"
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = output_dir.resolve()
    if alias.is_symlink():
        if alias.resolve() != expected:
            raise Stop("Путь out-y700 уже ссылается на другую папку. "
                       "Существующая ссылка сохранена: " + str(alias))
    elif alias.exists():
        raise Stop("Путь out-y700 уже занят. Его содержимое сохранено: " + str(alias))
    else:
        alias.symlink_to(os.path.relpath(output_dir, src), target_is_directory=True)
    return alias.name


def build_system(src, work, jobs, recipe, stamp):
    env = os.environ.copy()
    for key in ["JAVA_HOME", "ANDROID_JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT",
                "OUT_DIR_COMMON_BASE", "TARGET_PRODUCT", "TARGET_RELEASE",
                "TARGET_BUILD_VARIANT", "TARGET_BUILD_APPS", "NINJA_ARGS",
                "NINJA_EXTRA_ARGS", "SOONG_UI_NINJA_ARGS", "USE_RBE",
                "USE_REWRAPPER", "USE_GOMA"]:
        env.pop(key, None)
    product_file = work / "metadata/gsi-product-out.txt"
    output_dir = work / "out/gsi-vanilla-ext4"
    relative_out = output_directory_alias(src, output_dir)
    say("OUT_DIR: " + relative_out + " -> " + str(output_dir))
    env.update({
        "OUT_DIR": relative_out, "TMPDIR": str(work / "tmp"),
        "USE_CCACHE": "0", "USE_RBE": "false", "USE_REWRAPPER": "false",
        "USE_GOMA": "false", "NINJA_HIGHMEM_NUM_JOBS": "1",
        "SOONG_UI_NINJA_ARGS": "-j1",
        "Y700_BUILD_TARGET": TARGET, "Y700_BUILD_JOBS": str(jobs),
        "Y700_PRODUCT_OUT_FILE": str(product_file),
    })
    save_json(work / "metadata/gsi-build-started.json",
              {"target": TARGET, "jobs": jobs, "recipe": recipe, "started": stamp,
               "out_dir": relative_out, "physical_out_dir": str(output_dir)})
    streamed(["bash", "-c", BUILD_SHELL], src, env)
    product = Path(product_file.read_text().strip())
    if not product.is_absolute():
        product = src / product
    product = product.resolve()
    if not product.is_relative_to(output_dir.resolve()):
        raise Stop("PRODUCT_OUT оказался вне выбранной папки результата.")
    system = product / "system.img"
    if not system.is_file() or system.stat().st_size < 1024 * 1024:
        raise Stop("Сборка не создала system.img.")
    with system.open("rb") as f:
        f.seek(1024 + 56)
        if f.read(2) != b"\x53\xef":
            raise Stop("system.img не является ожидаемым RAW ext4-образом.")
    artifact = work / "out/artifacts" / ("lineage-23.2-vanilla-ext4-" + stamp)
    artifact.mkdir(parents=True)
    image = artifact / "system.img"
    run(["cp", "--reflink=auto", "--sparse=always", system, image])
    checksum = digest(image)
    (artifact / "SHA256SUMS").write_text(checksum + "  system.img\n")
    save_json(artifact / "build-info.json", {
        "target": TARGET, "recipe": recipe, "sha256": checksum,
        "size_bytes": image.stat().st_size, "filesystem": "ext4",
        "status": "experimental generic baseline; not device-tested",
        "kernel_built": False,
    })
    shutil.copy2(work / "metadata/source-lock.xml", artifact / "source-lock.xml")
    say("\nСборка завершена. Экспериментальный GSI: " + str(image))
    say("SHA-256: " + checksum)
    say("Этот образ ещё не проверен на TB321FU.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true",
                      help="проверить патчи на изолированных индексах; не менять исходники")
    mode.add_argument("--prepare-only", action="store_true",
                      help="подготовить патчи, SDK и TrebleApp без сборки system.img")
    parser.add_argument("disk", nargs="?", default="/run/media/ilya/SSD512")
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise Stop("Запусти обычным пользователем, без sudo.")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise Stop("Нужен Linux x86_64.")
    disk = Path(args.disk).absolute()
    if any(c.isspace() for c in str(disk)):
        raise Stop("Путь к дереву Android не должен содержать пробелы.")
    if not disk.is_dir() or not os.path.ismount(disk):
        raise Stop("Рабочий диск не смонтирован: " + str(disk))
    work = disk / "Y700-LineageOS"
    src = work / "source"
    lock_path = work / "metadata/source-lock.xml"
    if not (src / ".repo").is_dir() or not lock_path.is_file():
        raise Stop("Не найдены скачанные исходники и metadata/source-lock.xml.")
    if not (work / "metadata/download-complete").is_file():
        raise Stop("Загрузка исходников ещё не завершена.")
    try:
        jobs = int(os.environ.get("Y700_BUILD_JOBS", "2"))
    except ValueError:
        raise Stop("Y700_BUILD_JOBS должен быть целым числом от 1 до 4.")
    if not 1 <= jobs <= 4:
        raise Stop("Для этого сценария Y700_BUILD_JOBS должен быть от 1 до 4.")
    for directory in ["logs", "tmp", "metadata"]:
        (work / directory).mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_path = work / "logs" / ("build-gsi-" + stamp + ".log")
    global LOG
    with contextlib.ExitStack() as stack:
        locked(work / ".gsi-build.lock", stack)
        locked(work / ".download.lock", stack)
        LOG = stack.enter_context(log_path.open("w", encoding="utf-8"))
        say("LineageOS 23.2 Vanilla GSI / TB321FU, исходники ядра не используются.")
        say("Лог: " + str(log_path))
        try:
            java, _ = host_check(work, not args.check_only)
            projects, recipe = collect_recipe(src, lock_path)
            say(f"Цель: {TARGET}; задач компиляции: {jobs}")
            say(f"Патчей: {sum(len(p['patches']) for p in projects.values())}; "
                f"проектов: {len(projects)}")
            state_path = work / "metadata/gsi-prepared-v1/state.json"
            state = json.loads(state_path.read_text()) if state_path.is_file() else None
            if state and state.get("recipe") != recipe:
                raise Stop("Изменился рецепт или source-lock.xml. "
                           "Старое состояние сохранено; требуется отдельная проверка.")
            verify_sources(src, projects, state)
            if not state:
                state = preflight(src, work, projects, recipe, stamp)
            if args.check_only:
                say("\nПроверка завершена; исходники не изменены. "
                    "Если патчи были установлены раньше, проверено сохранённое состояние.")
                return
            install_patches(src, work, state)
            verify_sources(src, projects, state)
            sdk = prepare_sdk(work, src)
            build_app(src, work, java, sdk)
            if args.prepare_only:
                say("\nПатчи, Android SDK и TrebleApp готовы. "
                    "Для system.img повтори команду без --prepare-only.")
                return
            build_system(src, work, jobs, recipe, stamp)
        except BaseException as error:
            if not isinstance(error, KeyboardInterrupt):
                say("Ошибка: " + str(error))
            say("\nОстановлено. Лог: " + str(log_path))
            say("Повторный запуск продолжает сборку. Конфликты патчей требуют разбора "
                "указанного архива; они автоматически не пропускаются.")
            raise
        finally:
            LOG = None


if __name__ == "__main__":
    try:
        main()
    except (Stop, OSError, ET.ParseError, ValueError) as error:
        say("\nОшибка: " + str(error))
        sys.exit(1)
    except KeyboardInterrupt:
        say("\nПрервано пользователем.")
        sys.exit(130)
