"""
child_rutting_as_per_ca  (DLM table name) — CA only
  Lane-wise CA rows at the D2 reporting interval (rut depth: CA sheet, else IRC sheet, else overall, else config):
  the D4 10 m rut depths aggregated with the NSV formulas. Checked against the D2 lane values.
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/child_rutting_as_per_ca.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_child_as_per_ca
from common.output import run_table, standalone

KEY = 'child_rutting_as_per_ca'
TABLE = 'child_rutting_as_per_ca'


def build(prj):
    return build_child_as_per_ca(prj, 'rutting')


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
