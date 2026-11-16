"""
child_10m_cracking  (silver table list: child_10m, CA + IRC, 10 m)
  One row per lane per 10 m: CA row of master_cracking (D4 10 m cracking) + its IRC twin as irc_* columns, CA values
  copied to ca_*; threshold_name 'As per CA & IRC'; breach_flag = 1 when CA or IRC breaches;
  parent_id = the master_cracking_ca row of its 100 m.
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/child_10m_cracking.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_child_10m
from common.output import run_table, standalone

KEY = 'child_10m_cracking'
TABLE = 'child_10m_cracking'


def build(prj):
    return build_child_10m(prj, 'cracking', TABLE, 'master_cracking', config.CRACKING_PARENT_M, config.CRACKING_PARENT_BY)


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
