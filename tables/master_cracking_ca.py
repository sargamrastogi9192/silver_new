"""
master_cracking_ca  (silver table list: parent, CA, 100 m)
  One row per side (LHS / RHS; config.CRACKING_PARENT_BY 'lane' → per lane) per 100 m from the CA rows of
  master_cracking_child_100m (D4 'Cracking Lane Area @ 10 mtr' averaged per 100 m): cracking % = average of the
  side's lane values, area = total, breach = any lane breaches the CA threshold (D2). Image names: NSV logic.
  id {UPC}_master_cracking_ca_{LHS|RHS}_{start}; parent_id = record_id = {UPC}_{LHS|RHS}_{start}_{start+100}.
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/master_cracking_ca.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_side_parent
from common.output import run_table, standalone

KEY = 'master_cracking_ca'
TABLE = 'master_cracking_ca'


def build(prj):
    return build_side_parent(prj, 'cracking', TABLE, 'master_cracking_child_100m', config.CRACKING_PARENT_M, config.CRACKING_PARENT_BY)


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
