"""
master_cracking_irc  (silver table list: child, IRC, 100 m)
  One row per lane per 100 m: the 'As per IRC' rows of master_cracking_child_100m (IRC threshold and operator from
  D2). defect_id on breach rows = CA row's defect_id, else record_id; affected_length_ca 0;
  parent_id = the master_cracking_ca row of the same 100 m.
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/master_cracking_irc.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_child_irc100
from common.output import run_table, standalone

KEY = 'master_cracking_irc'
TABLE = 'master_cracking_irc'


def build(prj):
    return build_child_irc100(prj, 'cracking', TABLE, config.CRACKING_PARENT_M, config.CRACKING_PARENT_BY)


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
