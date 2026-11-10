"""Bind the installed entry point to the test server; never distributed."""
import os
import runpy
import sysconfig
from pathlib import Path

from skippo_cli import assets, core, public_config

public_config.PUBLIC_BASE = os.environ["TEST_SERVER"]
assets.ASSET_BASE = assets.CDN_BASE = os.environ["TEST_SERVER"]
core.REQUEST_TIMEOUT = 0.5
core.HUB = core.IDENTITY = core.TOKEN = core.FIRESTORE = os.environ["TEST_SERVER"]
runpy.run_path(str(Path(sysconfig.get_path("scripts")) / "skippo"), run_name="__main__")
