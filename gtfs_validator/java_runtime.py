"""Per-user Java selection, without installing Java or changing system PATH."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from .cache_store import cache_root


def settings_path() -> Path:
    override = os.environ.get('GTFS_VALIDATOR_SETTINGS_FILE')
    return Path(override).expanduser().resolve() if override else cache_root().parent / 'settings.json'


def find_java() -> str | None:
    path = settings_path()
    if path.exists():
        try:
            selected = json.loads(path.read_text(encoding='utf-8')).get('java_executable')
        except (OSError, ValueError, AttributeError) as exc:
            raise ValueError('Cannot read Java settings. Run configure_java.bat again.') from exc
        if selected:
            if not Path(selected).is_file():
                raise ValueError('Saved Java runtime moved or is missing. Run configure_java.bat again.')
            return str(Path(selected).resolve())
    return shutil.which('java')


def select_java(location: str) -> tuple[Path, str]:
    root = Path(location.strip().strip('"')).expanduser().resolve()
    candidates = [root] if root.is_file() else [root / 'bin' / 'java.exe', root / 'java.exe']
    if root.is_dir():
        ini = root / 'eclipse.ini'
        if ini.is_file():
            lines = ini.read_text(encoding='utf-8-sig').splitlines()
            if '-vm' in lines and lines.index('-vm') + 1 < len(lines):
                vm = Path(lines[lines.index('-vm') + 1].strip())
                vm = vm if vm.is_absolute() else root / vm
                candidates.insert(0, vm / 'java.exe' if vm.is_dir() else vm.with_name('java.exe'))
        candidates.extend(sorted(root.glob('plugins/org.eclipse.justj.openjdk.hotspot.jre.full.win32.*/jre/bin/java.exe'), reverse=True))
    for executable in candidates:
        if executable.name.lower() not in {'java.exe', 'java'} or not executable.is_file():
            continue
        output = subprocess.run([str(executable), '-version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        match = re.search(r'version\s+"(\d+)(?:\.(\d+))?', output.stdout)
        major = int(match[2] if match and match[1] == '1' else match[1]) if match else 0
        if output.returncode == 0 and major >= 17:
            return executable.resolve(), output.stdout.strip()
    raise ValueError('No working Java 17+ found. Enter the Eclipse folder containing eclipse.exe, or the full java.exe path.')


def save_java(location: str) -> tuple[Path, str]:
    executable, version = select_java(location)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # No batch script is generated or executed from user-provided text.
    path.write_text(json.dumps({'java_executable': str(executable)}, indent=2), encoding='utf-8')
    return executable, version


def main() -> int:
    print('One-time Java setup. No administrator rights or system PATH changes needed.')
    print('Use a runtime your agency permits running outside Eclipse.')
    try:
        location = input('Paste your Eclipse folder path (or java.exe path): ')
        executable, version = save_java(location)
        print(version)
        print(f'Saved: {executable}\nSettings: {settings_path()}')
        print('Now run setup_mobilitydata.bat once, then start_windows.bat normally.')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, EOFError) as exc:
        print(f'Java setup failed: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
