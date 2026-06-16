#!/usr/bin/python3
"""
Upstream linting introduced Python >= 3.14 exclusive syntax,
  specifically the removal of forward annotations and the removal of parentheses around exceptions.
This script rewrites the codebase to re-introduce support for Python 3.13 and aims to keep the
  amount of changes/diff to a minimum.
The tool itself must be run with Python >= 3.13. It requires a working development setup.

Copyright 2026 SUSE LLC <georg.pfuetzenreuter@suse.com>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import json
import re
import subprocess
from pathlib import Path

target_directories = [
        'authentik',
        'lifecycle',
        'packages',
        'tests',
]

def scan_ruff():
    """
    This finds files and line numbers for:
        - unquoted typing annotations
        - exception groups without parentheses
    """

    affected_files = {
            'annotations': set(),
            'exceptions': [],
    }

    result = subprocess.run(
        [
            'uv', 'run',
            'ruff', 'check',
            '--exit-zero',
            '--isolated',  # ignore configuration file
            '--select', 'F821', 
            '--target-version', 'py313', 
            '--output-format', 'json',
        ] + target_directories,
        capture_output=True,
        check=True,
        text=True,
    )
    
    try:
        ruff_errors = json.loads(result.stdout)

    except json.JSONDecodeError:
        print(result)
        print('Failed to parse Ruff output.')

        return affected_files

    for error in ruff_errors:
        file = error['filename']

        match error['code']:

            # unquoted typing annotations
            case 'F821':
                # add file if it isn't already included
                # line number are not relevant for these
                affected_files['annotations'].add(file)

            case 'invalid-syntax':
                match error['message']:
                    case 'Multiple exception types must be parenthesized on Python 3.13 (syntax was added in Python 3.14)': # noqa E501, length
                        print(error)
                        affected_files['exceptions'].append(
                                {
                                    'file': file,
                                    'row': error['location']['row'],
                                }
                        )

    return affected_files


def scan_type_checking():
    """
    This finds files containing the TYPE_CHECKING conditional.
    """

    affected_files = set()
    
    for directory in target_directories:

        for filepath in Path(directory).rglob('*.py'):
            try:
                content = filepath.read_text(encoding='utf-8')

                if '#!/usr/bin' in content:
                    continue

                if 'TYPE_CHECKING' in content and \
                    'from __future__ import annotations' not in content:

                    affected_files.add(str(filepath.absolute()))

            except Exception as e:
                print(f'Could not read {filepath}: {e}')
                raise

    return affected_files


def patch_annotations(files):
    """
    This injectrs a future import at the very top of the given files.
    """

    for file in files:
        filepath = Path(file)
        content = filepath.read_text(encoding='utf-8')
        
        # Safety check: avoid duplicating the import
        if 'from __future__ import annotations' in content:
            print(f'{file}: already contains future annotations import')
            continue

        filepath.write_text('from __future__ import annotations\n\n' + content, encoding='utf-8')

        print(f'{file}: added future annotations import')


def patch_exceptions(files):
    """
    This adds parentheses around exception groups.
    Could be optimized to not re-open files with multiple affected lines multiple times ...
    """

    pattern = re.compile(r'^(\s+)(except )(.*):$')

    for file_info in files:
        file = file_info['file']

        with open(file) as fh:
            lines = fh.readlines()

        line_number = file_info['row'] - 1
        problem = lines[line_number]

        lines[line_number], i = pattern.subn(r'\1\2(\3):', problem)

        if i == 0:
            continue

        print(f'{file}:{line_number}:\nold: {problem}new: {lines[line_number]}\n')

        with open(file, 'w') as fh:
            fh.writelines(lines)

def main():
    affected_files = scan_ruff()
    affected_files['annotations'] = affected_files['annotations'] | scan_type_checking()

    if not affected_files['annotations'] and not affected_files['exceptions']:
        print('Nothing to do.')
        return

    # exceptions must run first, as annotations shifts the line count
    patch_exceptions(affected_files['exceptions'])
    patch_annotations(affected_files['annotations'])

    print('\nDone, review status/diff.')


if __name__ == '__main__':
    main()
