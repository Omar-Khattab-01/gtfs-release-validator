"""Native file selection in an isolated process, suitable for the local web server."""
import json
import subprocess
import sys
import threading

KINDS = {'zip': ('GTFS export', '*.zip'), 'jar': ('MobilityData JAR', '*.jar'), 'csv': ('CSV file', '*.csv')}
_picker_lock = threading.Lock()


def pick_file(kind='zip'):
    if kind not in KINDS:
        raise ValueError('Unsupported file type')
    if not _picker_lock.acquire(blocking=False):
        raise ValueError('A file picker is already open. Choose a file or cancel it first.')
    try:
        result = subprocess.run([sys.executable, '-m', 'gtfs_validator.file_picker', kind],
                                capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise ValueError('The file picker is unavailable on this computer. Paste the file path instead.')
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise ValueError('File selection did not complete. Paste the file path or try Browse again.') from exc
    finally:
        _picker_lock.release()


def main():
    from tkinter import Tk, filedialog
    kind = sys.argv[1]
    title, pattern = KINDS[kind]
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        path = filedialog.askopenfilename(parent=root, title='Select ' + title,
                                          filetypes=[(title, pattern)])
        print(json.dumps({'path': path or ''}))
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
