"""Retired entry point for the paused experimental merge builder."""
import sys

if __name__ == "__main__":
    print("The merge builder is paused. Open start_windows.bat to inspect and validate exports.", file=sys.stderr)
    raise SystemExit(1)
