#!/usr/bin/env python3
"""Local-only initial/update/rollback assembly. Never reads a key or deploys."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess

sys.dont_write_bytecode = True
import odpt_release_contract as c
import odpt_generation_contract as g
from validate_odpt_generations import verify_inputs, expected_files, validate_transition, cli_parser, cli_inputs


def assemble(*, output, prune_release_ids=(), **inputs):
    output = c.safe_path(output)
    c.require(not os.path.lexists(output) and output.parent.is_dir(), 'output_exists_or_parent_missing')
    protected = [c.ROOT, c.safe_path(inputs['previous'])]
    if inputs.get('new_release') is not None:
        protected.append(c.safe_path(inputs['new_release']))
    for key in ('candidate', 'source'):
        value = (inputs.get('validation_inputs') or {}).get(key)
        if value is not None: protected.append(c.safe_path(value))
    c.require(all(not output.is_relative_to(p) for p in protected), 'output_inside_protected_input')
    old, new, clock = verify_inputs(**inputs)
    manifest = g.plan_manifest(old['manifest'], None if new is None else new['manifest'],
        operation=inputs['operation'], now=clock, previous_digest=inputs['expected_previous_digest'],
        rollback_release_id=inputs.get('rollback_release_id'), prune_release_ids=prune_release_ids)
    files = expected_files(manifest, old, new)
    c.require(all(len(raw) <= c.MAX_FILE_BYTES for raw in files.values())
              and sum(map(len, files.values())) <= c.MAX_TOTAL_BYTES, 'assembled_size_limit')
    stage = Path(tempfile.mkdtemp(prefix='.odpt-generations-', dir=output.parent))
    try:
        for name, raw in files.items():
            path = stage / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        result = validate_transition(stage, prune_release_ids=prune_release_ids, **inputs)
        # Compare to the assembly's ORIGINAL observations as well as the validator's.
        c.require(g.read_tree(inputs['previous'])['digest'] == old['digest'], 'previous_artifact_changed')
        if new is not None:
            c.require(g.read_tree(inputs['new_release'])['digest'] == new['digest'], 'new_release_changed')
        c.require(not os.path.lexists(output), 'output_exists')
        os.rename(stage, output)
        return result
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = cli_parser(__doc__); parser.add_argument('--output', type=Path, required=True)
    try:
        print(c.canonical(assemble(**cli_inputs(parser.parse_args()))).decode()); return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError, subprocess.SubprocessError):
        print('v2 generation assembly failed; no deployment performed', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
