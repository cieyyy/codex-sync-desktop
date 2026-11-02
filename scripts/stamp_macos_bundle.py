"""Stamp the macOS bundle with the same version as the Python application."""
from pathlib import Path
import plistlib
import sys
import tomllib


root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
bundle = Path(sys.argv[1])
plist = bundle / "Contents" / "Info.plist"
metadata = plistlib.loads(plist.read_bytes())
metadata.update(
    CFBundleShortVersionString=version,
    CFBundleVersion=version,
    CFBundleIdentifier="com.cieyyy.codex-sync-desktop",
)
plist.write_bytes(plistlib.dumps(metadata))
