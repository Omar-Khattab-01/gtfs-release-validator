"""Run native dialogs on their own main thread (important for Windows/macOS Tk)."""
import json
import sys


def main():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        kind = sys.argv[1]
        if kind == 'folder':
            path = filedialog.askdirectory(parent=root, title='Choose a folder for merged GTFS exports')
        else:
            types = {'zip': [('GTFS ZIP archive', '*.zip')], 'policy': [('Merge policy JSON', '*.json')],
                     'csv': [('Route-sort CSV', '*.csv')]}[kind]
            path = filedialog.askopenfilename(parent=root, title='Select a local GTFS input', filetypes=types)
        print(json.dumps({'path': path}, ensure_ascii=True))
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
