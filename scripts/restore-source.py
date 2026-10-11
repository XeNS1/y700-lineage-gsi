#!/usr/bin/env python3
"""Restore exported source deltas onto their exact upstream revisions."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent


def require(value, message):
    if not value:
        raise RuntimeError(message)


def safe(root, name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and '.git' not in p.parts, 'Unsafe path')
    target = root/name
    require(target.parent.resolve().is_relative_to(root.resolve()), 'Path escapes source tree: ' + name)
    return target


def git(repo, *args):
    return subprocess.run(['git', *map(str, args)], cwd=repo, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})


def matches(path, info):
    kind = info['kind']
    if kind == 'absent':
        return not path.exists() and not path.is_symlink()
    if kind == 'symlink':
        return path.is_symlink() and os.readlink(path) == info['target']
    if not path.is_file() or path.is_symlink():
        return False
    return (hashlib.sha256(path.read_bytes()).hexdigest() == info['sha256']
            and bool(path.stat().st_mode & 0o111) == bool(info['mode'] & 0o111))


def restore(source):
    source = source.resolve()
    index = json.loads((ROOT/'export-index.json').read_text())
    require(index.get('format') == 1, 'Unknown export format')
    root = ET.parse(ROOT/index['baseline_manifest']).getroot()
    default = root.find('default')
    defaults = {} if default is None else default.attrib
    # Verify every upstream revision, not just the repositories containing patches.
    for project in root.findall('project'):
        name = project.get('path', project.get('name'))
        repo = safe(source, name)
        expected = project.get('revision', defaults.get('revision'))
        result = git(repo, 'rev-parse', 'HEAD')
        require(result.returncode == 0 and result.stdout.decode().strip() == expected,
                'Wrong upstream revision: ' + name)
    plan = []
    for item in index['projects']:
        repo = safe(source, item['path'])
        patch = safe(ROOT, item['patch'])
        require(hashlib.sha256(patch.read_bytes()).hexdigest() == item['sha256'], 'Modified patch')
        expected = item['expected']
        already = all(matches(safe(repo, path), info) for path, info in expected.items())
        if already:
            require(git(repo, 'apply', '--reverse', '--check', patch).returncode == 0,
                    'Partially modified patch result: ' + item['path'])
            continue
        # Do not merge a patch into unrelated local edits, including staged changes.
        require(git(repo, 'diff', '--quiet', 'HEAD', '--').returncode == 0,
                'Local tracked changes: ' + item['path'])
        require(not git(repo, 'ls-files', '-u', '-z').stdout, 'Git conflicts: ' + item['path'])
        check = git(repo, 'apply', '--check', '--whitespace=nowarn', patch)
        require(check.returncode == 0, 'Patch preflight failed: ' + item['path'] + '\n' +
                check.stderr.decode(errors='replace'))
        plan.append((repo, patch, item))
    for name, info in index['payload'].items():
        src = safe(ROOT/'payload', name)
        dst = safe(source, name)
        require(matches(src, info), 'Modified exported source: ' + name)
        require(not dst.exists() and not dst.is_symlink() or matches(dst, info),
                'Different local source file: ' + name)
    # Preflight above is complete before the first write.
    for repo, patch, item in plan:
        result = git(repo, 'apply', '--whitespace=nowarn', patch)
        require(result.returncode == 0, 'Apply failed: ' + result.stderr.decode(errors='replace'))
        require(all(matches(safe(repo, p), v) for p, v in item['expected'].items()),
                'Restored source differs: ' + item['path'])
    for name, info in index['payload'].items():
        src = safe(ROOT/'payload', name)
        dst = safe(source, name)
        if matches(dst, info):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if info['kind'] == 'symlink':
            dst.symlink_to(info['target'])
        else:
            dst.write_bytes(src.read_bytes())
            dst.chmod(info['mode'])
    print('PASS: patches and new source files restored; upstream revisions unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    try:
        restore(Path(parser.parse_args().source))
    except (RuntimeError, OSError, ValueError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
