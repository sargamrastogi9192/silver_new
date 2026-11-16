"""
master_roughness  (DLM table name) — CA only
  One row per side (LHS = all L lanes, RHS = all R lanes) per 1 km from the CA rows of master_roughness_parent:
  value = average of the side's lane 1 km BI; breach = any lane breaches the CA threshold;
  rating_ca / rating_irc of the lane with the highest value; id = {UPC}_master_roughness_{LHS|RHS}_{km}.
  parent_id = record_id = {UPC}_{LHS|RHS}_{km start}_{km end} (children link to it).
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/master_roughness.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_side_parent
from common.output import run_table, standalone

KEY = 'master_roughness'
TABLE = 'master_roughness'


def build(prj):
    return build_side_parent(prj, 'roughness')


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
