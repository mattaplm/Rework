"""One-off/CLI import of the Hardware workbook -- same as Admin -> Import from
Excel's Hardware card (see services/hardware_import.py).

    python import_hardware_log.py "Scrap Rework -  Use this one V2.xlsx"
"""

import sys

import db
from services import hardware_import

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    db.init_db()
    print(hardware_import.import_workbook(sys.argv[1]))
