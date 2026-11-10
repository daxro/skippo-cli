"""Bind the installed entry point to the test server; never distributed."""
import os
import runpy
import sysconfig
from pathlib import Path

from skippo_cli import core

core.REQUEST_TIMEOUT = 0.5
core.HUB = core.IDENTITY = core.TOKEN = core.FIRESTORE = os.environ["TEST_SERVER"]
runpy.run_path(str(Path(sysconfig.get_path("scripts")) / "skippo"), run_name="__main__")
