"""
master_rutting  (DLM table name) — CA only
  One row per side per 1 km from the CA rows of master_rutting_parent: value = average of the side's lane 1 km
  rut depth; breach = any lane breaches the CA threshold; rating_ca / rating_irc of the lane with the highest value.
  The 8 CA / IRC columns of the given column list are written as NULL (config.PARENT_EXTRA_COLUMNS).
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/master_rutting.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_side_parent
from common.output import run_table, standalone

KEY = 'master_rutting'
TABLE = 'master_rutting'


def build(prj):
    return build_side_parent(prj, 'rutting')


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
