#!/usr/bin/env python3
"""Rebuild the TrebleApp APK from its exported source, without applying GSI patches."""
import argparse
import importlib.util
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    work = Path(parser.parse_args().project).resolve()
    builder = Path(__file__).with_name('y700-build-gsi.py')
    spec = importlib.util.spec_from_file_location('y700_recipe', builder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = work/'source'
    for name in ('logs', 'tmp', 'metadata'):
        (work/name).mkdir(parents=True, exist_ok=True)
    java, _ = module.host_check(work, True)
    sdk = module.prepare_sdk(work, source)
    module.build_app(source, work, java, sdk)
    print('TrebleApp rebuilt from source. No GSI patches were applied again.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
