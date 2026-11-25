import os
import subprocess
import sys


def test_kernel_limits_writes_to_configured_directories(tmp_path):
    state, workspace, outside = (tmp_path / name for name in ("state", "workspace", "outside"))
    for directory in (state, workspace, outside):
        directory.mkdir()
    script = """
import errno
import os
import sys
from pathlib import Path
from nexus.landlock import restrict_writes

state, workspace, outside = map(Path, sys.argv[1:])
fd = os.open(workspace, os.O_DIRECTORY | os.O_RDONLY)
restrict_writes(state, [fd])
for root in (state, workspace):
    (root / 'allowed.txt').write_text('inside')
try:
    (outside / 'denied.txt').write_text('outside')
except OSError as error:
    assert error.errno in (errno.EACCES, errno.EPERM)
else:
    raise AssertionError('Kernel allowed a write to an unauthorized directory')
"""
    subprocess.run(
        [sys.executable, "-c", script, str(state), str(workspace), str(outside)],
        env=os.environ.copy(),
        check=True,
    )
    assert (state / "allowed.txt").is_file()
    assert (workspace / "allowed.txt").is_file()
    assert not (outside / "denied.txt").exists()
