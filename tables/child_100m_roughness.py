"""
child_100m_roughness  (DLM table name) — IRC only
  One row per lane per 100 m (fixed): the 'As per IRC' rows of master_roughness_child_100m (IRC threshold and
  operator from D2). defect_id on breach rows = CA row's defect_id, else record_id; affected_length_ca 0;
  road_condition = rating_irc, else Poor / Good from the IRC breach.
Written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
Run alone:  python tables/child_100m_roughness.py [--no-excel]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from common.hierarchy import build_child_irc100
from common.output import run_table, standalone

KEY = 'child_100m_roughness'
TABLE = 'child_100m_roughness'


def build(prj):
    return build_child_irc100(prj, 'roughness')


def run(prj, write=True):
    return run_table(TABLE, build, prj, write, apply_finalize=False, folder=config.HIERARCHY_FOLDER, key=KEY)


if __name__ == '__main__':
    standalone(run)
