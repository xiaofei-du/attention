"""Exercise the real CLI without launching audible background workers in tests.

Queue/worker integration uses real stores and injected playback in test_runtime.
Only the detached process launch is replaced here; parsing and hook handling run.
"""

from nkc.install import PROJECT, PYTHON


def quiet_cli_prefix():
    return [PYTHON, '-c', '''
import runpy
import sys
from nkc import runtime
original_hook = runtime.handle_hook
def quiet_hook(action, event, store, **kwargs):
    return original_hook(action, event, store, start_worker=lambda root: None, **kwargs)
runtime.handle_hook = quiet_hook
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
''', str(PROJECT / 'run.py')]
