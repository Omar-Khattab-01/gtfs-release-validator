"""Windows-friendly entry point. Run `python merge_gtfs.py --help`."""
import sys
from gtfs_validator.__main__ import main

if __name__=='__main__':
    sys.argv.insert(1,'build-release')
    main()
