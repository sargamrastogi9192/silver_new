"""
DLM LHS / RHS hierarchy tables (new DLM table names), built from the finished NSV lane-wise tables.
Values (metric, BI / IRI, thresholds, breach, ratings) are NOT recalculated: they come from the NSV tables, so the
NSV formulas (e.g. roughness BI = 630 × IRI^1.12) stay as they are. Only the layout changes (DLM notebook logic).

  master_<d>             parent: one row per side (LHS = all L lanes, RHS = all R lanes) per 1 km, CA only.
                         Built from the CA rows of master_<d>_parent. value = average of the side's lane values;
                         breach = any lane breaches; rating_ca / rating_irc of the lane with the highest value.
  child_<d>_as_per_ca    lane-wise CA rows at the D2 CA reporting interval (CA defect column, else CA overall, else
                         config default + DQ gate FAIL; the IRC sheet is never used):
                         the D4 10 m rows aggregated to that interval with the NSV formulas
                         (roughness: average lane IRI of the block, then BI = 630 × IRI^1.12 — as D2):
                         100 m → master_<d>_child_100m CA rows; 1000 m → master_<d>_parent CA rows;
                         any other interval → the 100 m build re-run at that interval.
                         Every block is checked against the D2 lane value (log + dq/<table>_vs_d2.csv).
  child_10m_<d>          lane-wise 10 m: CA row of master_<d>_child_10m + the IRC twin row as irc_* columns.
  child_100m_<d>         lane-wise 100 m, IRC only: the 'As per IRC' rows of master_<d>_child_100m.
  Defects: roughness, rutting, ravelling (parent + as_per_ca + 10 m + 100 m), pothole (one row per pothole) and
  cracking as in the silver table list: master_cracking_ca (parent, CA, 100 m), master_cracking_irc (child, IRC,
  100 m), child_10m_cracking (CA + IRC, 10 m); parent per side (config.CRACKING_PARENT_BY). Cracking 'measures' use
  the DLM keys filled from D4. Image names: NSV logic kept (distinct names joined).
  master_pothole         one row per pothole (defect records) from the NSV potholes (master_pothole, dlm_kpi),
                         DLM pothole columns; NSV values, image names and severity breach rule unchanged. No child.
  All of them are written to <UPC>/dlm_kpi_new (config.HIERARCHY_FOLDER).
  Children: side = LHS / RHS, parent_id = {UPC}_{LHS|RHS}_{km start}_{km end} (= id of the side parent row).
"""
import json

import numpy as np
import pandas as pd

import config
from common.output import built_table
from common.utils import num

# Column list of the DLM defect tables (fixed order). Columns NSV does not produce are written as NULL.
BASE_COLUMNS = """
id collection_name defect_base level standard defect_id display_defect_id source_defect_id parent_id record_id
upc upc_code nh_number section_code zone phase cycle source_system sources defect_type type_of_defect category
severity pavement_type pci lane breach_flag metric_name metric_value threshold_name threshold_value total_children
length_m area_sqm start_chainage end_chainage defect_chainage start_lat start_long end_lat end_long defect_lat
defect_long datetime observed_at survey_start_date survey_end_date image_name image_url image_urls remarks
is_duplicate nsv dams dashcam dlm project_details created_at updated_at side carriageway direction
parent_start_chainage parent_end_chainage reporting_interval_m segment_count roughness_bi iri_value iri_condition
rating_ca rating_irc defect_type_filter has_standard_defect standard_flags thresholds measures run_date detected_on
project_id region_id piu_id state_id zone_id contractor_id ae_ie_id total_count_of_pothole total_count_of_cracking
count_of_others_defects affected_length total_length affected_length_ca affected_length_irc road_condition
""".split()

def _swap(cols, old, new):
    i = cols.index(old[0])
    return [c for c in cols[:i] if c not in old] + new + [c for c in cols[i:] if c not in old]


_COUNTS = ('total_count_of_pothole', 'total_count_of_cracking', 'count_of_others_defects')
# rutting: roughness_bi + iri_value → rutting_avg (DLM column lists)
RUTTING_COLUMNS = _swap(BASE_COLUMNS, ['roughness_bi', 'iri_value'], ['rutting_avg'])
# cracking: roughness_bi + iri_value → cracking_pct, no count columns
CRACKING_COLUMNS = [c for c in _swap(BASE_COLUMNS, ['roughness_bi', 'iri_value'], ['cracking_pct']) if c not in _COUNTS]
# ravelling: roughness_bi + iri_value → ravelling_area (ravelling %), count columns kept
RAVELLING_COLUMNS = _swap(BASE_COLUMNS, ['roughness_bi', 'iri_value'], ['ravelling_area'])
DEFECT_COLUMNS = {'roughness': BASE_COLUMNS, 'rutting': RUTTING_COLUMNS, 'cracking': CRACKING_COLUMNS,
                  'ravelling': RAVELLING_COLUMNS}


def columns_of(defect):
    return DEFECT_COLUMNS[defect]


# master_pothole: same list without the roughness and count columns
POTHOLE_COLUMNS = [c for c in BASE_COLUMNS if c not in ('roughness_bi', 'iri_value', 'total_count_of_pothole',
                                                         'total_count_of_cracking', 'count_of_others_defects')]
TEN_M_EXTRA = ['irc_threshold_value', 'irc_breach_flag', 'irc_rating', 'irc_road_condition',
               'ca_threshold_value', 'ca_breach_flag', 'ca_rating', 'ca_road_condition']
# master_rutting: the column list given for it also has the 8 CA / IRC columns of the 10 m table (written as NULL —
# a 1 km side parent is CA only); config.PARENT_EXTRA_COLUMNS lists the parents that get them
PARENT_EXTRA = {d: TEN_M_EXTRA for d in getattr(config, 'PARENT_EXTRA_COLUMNS', [])}
KM = int(config.PARENT_LENGTH_M)
KM_DEFAULT = KM


# ── helpers ──────────────────────────────────────────────────────────────────
def _lane_key(lane):
    s = str(lane).strip().upper()
    return (s[:1], int(s[1:]) if s[1:].isdigit() else 99)


def side_of(lane):
    """L… → LHS, R… → RHS."""
    s = pd.Series(lane, dtype=object).astype(str).str.strip().str.upper()
    return np.where(s.str.startswith('L'), 'LHS', np.where(s.str.startswith('R'), 'RHS', None))


def _lo_hi(df):
    s, e = num(df['start_chainage']), num(df['end_chainage'])
    return np.minimum(s, e), np.maximum(s, e)


def side_parent_cols(df, prj, block=None, by='side'):
    """side + link to the parent row: parent_id = {UPC}_{LHS|RHS}_{block start}_{block end} (DLM; block = 1 km).
    by='lane' links to a lane-wise parent instead ({UPC}_{L1}_{start}_{end}) — cracking, config.CRACKING_PARENT_BY."""
    block = int(block or KM_DEFAULT)
    lo, _ = _lo_hi(df)
    b = (np.floor(lo / block) * block).astype('Int64')
    df['side'] = side_of(df['lane'])
    key = df['side'] if by == 'side' else df['lane'].astype(str).str.upper()
    df['parent_start_chainage'] = b
    df['parent_end_chainage'] = b + block
    df['parent_id'] = [f"{prj.upc}_{s}_{int(k)}_{int(k) + block}" if s is not None and pd.notna(k) else None
                       for s, k in zip(key, b)]
    return df


def keep_rating(df, std):
    """CA-only tables: rating_irc NULL; IRC-only tables: rating_ca NULL (the other standard does not apply)."""
    df['rating_irc' if std == 'ca' else 'rating_ca'] = None
    return df


def to_columns(df, columns):
    """Exactly these columns in this order; missing ones added as NULL, others dropped."""
    df = df.copy()
    for c in columns:
        if c not in df.columns:
            df[c] = None
    return df[columns]


def _ca_rows(df):
    return df[df['threshold_name'].fillna('') == 'As per CA'].copy()


def _sort_children(df):
    df = df.assign(_lk=df['lane'].map(_lane_key))
    return df.sort_values(['side', '_lk', 'start_chainage'], kind='mergesort').drop(columns='_lk').reset_index(drop=True)


# ── parent: master_<d> (LHS / RHS per 1 km) ─────────────────────────────────
def build_side_parent(prj, defect, table=None, src_key=None, block=None, by='side'):
    """Parent rows from the CA rows of an NSV table: one row per side (or per lane, by='lane') per block.
    Default = DLM master_<defect>: master_<defect>_parent, 1 km, LHS / RHS."""
    table = table or f'master_{defect}'
    KM = int(block) if block else KM_DEFAULT          # parent block size (1 km; cracking 100 m)
    cols = columns_of(defect) + PARENT_EXTRA.get(defect, [])
    src = built_table(prj, src_key or f'master_{defect}_parent')
    if src is None or src.empty:
        return pd.DataFrame(columns=cols)
    ca = _ca_rows(src)
    ca['_side'] = side_of(ca['lane'])
    ca['_grp'] = ca['_side'] if by == 'side' else ca['lane'].astype(str).str.upper()
    ca['_lo'], ca['_hi'] = _lo_hi(ca)
    ca['_km'] = (np.floor(ca['_lo'] / KM) * KM).astype('int64')
    ca['_lk'] = ca['lane'].map(_lane_key)
    ca = ca[ca['_side'].notna()].sort_values(['_side', '_km', '_lk'], kind='mergesort').reset_index(drop=True)

    rows = []
    for (grp, km), g in ca.groupby(['_grp', '_km'], sort=False):
        side = g['_side'].iloc[0]
        first, last = g.loc[g['_lo'].idxmin()], g.loc[g['_hi'].idxmax()]
        mv = num(g['metric_value'])
        lane_bf = num(g['breach_flag'])
        bf = int(lane_bf.max()) if lane_bf.notna().any() else None       # no D2 threshold → NULL (NSV rule)
        worst = g.loc[mv.idxmax()] if mv.notna().any() else first
        pav = sorted(set(g['pavement_type'].dropna()))
        pid = f"{prj.upc}_{grp}_{km}_{km + KM}"
        _sum = lambda c: float(num(g[c]).fillna(0).sum()) if c in g else 0.0
        thr = num(g['threshold_value']).dropna()
        rec = first.to_dict()
        rec.update({
            'id': f"{prj.upc}_{table}_{grp}_{km}", 'collection_name': table, 'level': 'parent',
            'lane': grp, 'side': side, 'direction': 'Increasing' if side == 'LHS' else 'Decreasing',
            'parent_id': pid, 'record_id': pid, 'source_defect_id': pid,
            'defect_id': pid if bf == 1 else None, 'display_defect_id': None,
            'metric_value': round(float(mv.mean()), 6) if mv.notna().any() else None,
            'breach_flag': bf, 'threshold_name': 'As per CA',
            'threshold_value': float(thr.iloc[0]) if len(thr) else None,
            'total_children': int(len(g)), 'segment_count': int(_sum('segment_count')),
            'start_chainage': first['_lo'], 'end_chainage': last['_hi'],
            'length_m': float(last['_hi'] - first['_lo']), 'total_length': _sum('length_m'),
            'defect_chainage': (first['_lo'] + last['_hi']) / 2,
            'start_lat': first.get('start_lat'), 'start_long': first.get('start_long'),
            'end_lat': last.get('end_lat'), 'end_long': last.get('end_long'),
            'defect_lat': first.get('start_lat'), 'defect_long': first.get('start_long'),
            'pavement_type': pav[0] if len(pav) == 1 else ('Hybrid' if pav else None),
            'parent_start_chainage': km, 'parent_end_chainage': km + KM, 'reporting_interval_m': KM,
            'rating_ca': worst.get('rating_ca'), 'rating_irc': worst.get('rating_irc'),
            'road_condition': None if bf is None else ('Bad' if bf else 'Good'),
            'area_sqm': _sum('area_sqm'),
            'affected_length': _sum('affected_length'), 'affected_length_ca': _sum('affected_length'),
            'affected_length_irc': 0.0,
            'measures': json.dumps({
                'side': side, 'lanes': [str(l) for l in g['lane']],
                'lane_values': {str(l): (None if pd.isna(v) else round(float(v), 6)) for l, v in zip(g['lane'], mv)},
                'lane_breach': {str(l): (None if pd.isna(b) else int(b)) for l, b in zip(g['lane'], lane_bf)},
                'calculation': f"{grp} {km}-{km + KM}: value = average of {len(g)} lane {'1 km' if KM == 1000 else f'{KM} m'} values; "
                               f"breach if any lane breaches the CA threshold "
                               f"({float(thr.iloc[0]) if len(thr) else 'not in D2'})"}),
        })
        if defect == 'cracking':
            rec['cracking_pct'] = rec['metric_value']                  # DLM: cracking_pct = side value
            names, urls = _group_image_pairs(g)                        # NSV image names / paths of the lanes
            rec['image_name'] = config.IMAGE_SEPARATOR.join(names) if names else None
            rec['image_urls'] = urls or None
        rows.append(rec)
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    out = keep_rating(out, 'ca')                                   # parent is CA only → rating_irc NULL
    if PARENT_EXTRA.get(defect):                                   # master_rutting: ca_* filled, irc_* NULL
        out['ca_threshold_value'] = num(out['threshold_value'])
        out['ca_breach_flag'] = out['breach_flag']
        out['ca_rating'] = out['rating_ca']
        out['ca_road_condition'] = out['road_condition']
    out['_lk'] = out['lane'].map(_lane_key)
    out = out.sort_values(['side', 'start_chainage', '_lk'], kind='mergesort').drop(columns='_lk')
    out['breach_flag'] = out['breach_flag'].astype('Int64')
    return to_columns(out, cols)


# ── child_<d>_as_per_ca (lane-wise, CA interval of D2) ──────────────────────
def ca_interval(prj, defect):
    """(interval m, where it came from) for child_<d>_as_per_ca — D2 'Comparison as per CA' ONLY (the IRC sheet is
    never used in place of CA):
       1) CA sheet 'Current Cycle | <defect> | Reporting Interval'
       2) CA sheet 'Overall Reporting Interval'
       3) no CA interval (e.g. no CA sheet) → config.CHILD_AS_PER_CA_DEFAULT_M (100 m; None → table empty)
          and the DQ gate 'as_per_ca_interval' is FAIL for the defect."""
    tries = [] if defect == 'pothole' else [('CA', defect, f'D2 Comparison as per CA, {defect}')]
    tries += [('CA', 'overall', 'D2 Comparison as per CA, Overall Reporting Interval')]
    for std, col, label in tries:
        iv = prj.d2_interval(std, col)
        if iv:
            return int(iv), label
    why = 'no D2 CA sheet' if prj.d2_ca.empty else 'no CA reporting interval in D2'
    d = config.CHILD_AS_PER_CA_DEFAULT_M
    return (int(d), f'config default ({why}; IRC not used)') if d else (None, f'{why}; IRC not used')


# D2 value column group per defect ('Current Cycle | <group> | L1')
_D2_VALUE_GROUP = {'roughness': 'roughness bi', 'rutting': 'rut depth', 'cracking': 'cracking lane area',
                   'ravelling': 'ravelling'}


def check_vs_d2(prj, defect, df, iv, table):
    """metric_value of every lane / block vs the D2 lane value of the same block (current cycle).
       D2 sheet: CA only (IRC is never used in place of CA). Prints match % per lane and writes
       every mismatch to <out>/dq/<table>_vs_d2.csv. Tolerance = config.DQ_TOLERANCE_BY_DEFECT / DQ_TOLERANCE."""
    import os
    from common.utils import norm_name, pick
    grp = _D2_VALUE_GROUP.get(defect)
    d2, sheet = None, 'CA'                    # as per CA → compared with the D2 CA sheet only (never IRC)
    x = prj.d2_ca
    if x is not None and not x.empty and grp and any(f'current cycle | {grp} |' in norm_name(c) for c in x.columns):
        d2 = x
    if d2 is None:
        print(f"  {table} vs D2: no D2 CA sheet / no CA '{grp}' values → not checked (IRC sheet not used)")
        return
    tol = config.DQ_TOLERANCE_BY_DEFECT.get(defect, config.DQ_TOLERANCE)
    st = num(d2[pick(list(d2.columns), 'chainage', 'start')])
    rows, mism = [], []
    for lane in sorted(df['lane'].dropna().unique(), key=_lane_key):
        col = next((c for c in d2.columns if norm_name(c) == f'current cycle | {grp} | {lane.lower()}'), None)
        if col is None:
            continue
        ref = pd.DataFrame({'b': (st // iv * iv), 'd2': num(d2[col])}).dropna()
        ref = ref.groupby('b', as_index=False)['d2'].first()
        sv = df[df['lane'] == lane]
        sv = pd.DataFrame({'b': num(sv['start_chainage']) // iv * iv, 'silver': num(sv['metric_value'])})
        m = ref.merge(sv, on='b', how='left')
        ok = (m['d2'] - m['silver']).abs() <= tol
        rows.append((lane, len(m), int(ok.sum())))
        bad = m[~ok].copy()
        if len(bad):
            bad['lane'] = lane
            bad['diff'] = (bad['silver'] - bad['d2']).abs()
            mism.append(bad)
    tot, hit = sum(r[1] for r in rows), sum(r[2] for r in rows)
    if not tot:
        print(f"  {table} vs D2 ({sheet} sheet): D2 has no current-cycle '{grp}' values → nothing to compare")
        return
    print(f"  {table} vs D2 ({sheet} sheet, {iv} m, tolerance {tol:g}): {hit:,}/{tot:,} blocks match "
          f"({100.0 * hit / tot if tot else 0:.1f}%) | " + ", ".join(f"{l} {h}/{n}" for l, n, h in rows))
    if mism:
        out = pd.concat(mism, ignore_index=True)[['lane', 'b', 'd2', 'silver', 'diff']].rename(columns={'b': 'block_start'})
        os.makedirs(os.path.join(prj.out_dir, 'dq'), exist_ok=True)
        out.to_csv(os.path.join(prj.out_dir, 'dq', f'{table}_vs_d2.csv'), index=False)


def _rows_at_interval(prj, defect, iv):
    """NSV lane-wise CA + IRC rows of the defect at interval iv (same formulas as the 100 m table)."""
    from common.segments import build_linear_table
    from common.finalize import finalize
    old = config.CHILD_100M
    config.CHILD_100M = iv
    try:
        if defect == 'cracking':
            from tables.master_cracking import build_level
            raw = build_level(prj, 'master_cracking_child_100m', 'child_100m')
        else:
            raw = build_linear_table(prj, defect, 'child_100m')
        df = finalize(raw, f'master_{defect}_child_100m', prj)
    finally:
        config.CHILD_100M = old
    # PCI of a block = mean of its 10 m PCI values (same rule as 100 m / 1 km)
    p10 = prj.pci_lookup[10].rename('pci').reset_index()
    p10['ch'] = p10['ch'] // iv * iv
    look = p10.groupby(['lane', 'ch'])['pci'].mean().round(4)
    key = pd.MultiIndex.from_arrays([df['lane'], num(df['start_chainage']).astype('int64') // iv * iv])
    df['pci'] = look.reindex(key).values
    df['id'] = df['id'].str.replace(f'master_{defect}_child_100m', f'master_{defect}_child_{iv}m', regex=False)
    return df


def build_child_as_per_ca(prj, defect):
    table = f'child_{defect}_as_per_ca'
    iv, how = ca_interval(prj, defect)
    if not iv:
        print(f"  WARNING: {table}: {how} and config.CHILD_AS_PER_CA_DEFAULT_M is None → table left empty")
        return pd.DataFrame(columns=columns_of(defect))
    if iv == int(config.CHILD_100M):
        src_t = f'master_{defect}_child_100m'
        src = built_table(prj, src_t)
    elif iv == KM:
        src_t = f'master_{defect}_parent'
        src = built_table(prj, src_t)
    else:
        src_t = f'master_{defect}_child_{iv}m'
        src = _rows_at_interval(prj, defect, iv)
    print(f"  CA reporting interval {iv} m ({how}) → CA rows of {src_t}")
    if src is None or src.empty:
        return pd.DataFrame(columns=columns_of(defect))
    out = _ca_rows(src)
    check_vs_d2(prj, defect, out, iv, table)
    out['id'] = out['id'].str.replace(src_t, table, regex=False)
    out['collection_name'] = table
    out['level'] = 'child_as_per_ca'
    out['reporting_interval_m'] = iv
    out['display_defect_id'] = None
    out = keep_rating(out, 'ca')                                   # CA only → rating_irc NULL
    out = side_parent_cols(out, prj)
    return to_columns(_sort_children(out), columns_of(defect))


def _crack_measures(df, level):
    """DLM cracking 'measures' keys, filled from D4: cracking_pct, crack_area_sqm, lane_area_sqm (3.5 × length),
    crack_count / avg_corrected_width_mm / avg_width_mm (DLM takes these from the backup crack list; D4 has no
    individual cracks → NULL), segments, calculation."""
    out = []
    for pct, area, ln, seg, st, en in zip(num(df['metric_value']), num(df['area_sqm']), num(df['length_m']),
                                          num(df['segment_count']), num(df['start_chainage']), num(df['end_chainage'])):
        ln = float(ln) if pd.notna(ln) else None
        m = {'cracking_pct': None if pd.isna(pct) else round(float(pct), 6),
             'crack_area_sqm': None if pd.isna(area) else round(float(area), 6),
             'lane_area_sqm': round(config.LANE_AREA_SQM / config.CHILD_10M * ln, 4) if ln else None,
             'crack_count': None, 'avg_corrected_width_mm': None, 'avg_width_mm': None}
        if level == 'child_10m':
            m['calculation'] = ("Cracking % = D4 'Cracking Lane Area (%) @ 10 mtr'; crack area = D4 'Cracking Lane Area "
                                "(sq. m.) @ 10 mtr'")
        else:
            m['segments'] = None if pd.isna(seg) else int(seg)
            m['calculation'] = (f"Cracking % = average of the D4 10 m cracking % over {int(st) if pd.notna(st) else ''}-"
                                f"{int(en) if pd.notna(en) else ''} (blank 10 m rows left out, as D2); "
                                f"crack area = sum of the 10 m sq. m.")
        out.append(json.dumps(m))
    return out


# ── child_10m_<d> (CA + IRC columns) ─────────────────────────────────────────
def build_child_10m(prj, defect, table=None, src_key=None, block=None, by='side'):
    table = table or f'child_10m_{defect}'
    src = built_table(prj, src_key or f'master_{defect}_child_10m')
    if src is None or src.empty:
        return pd.DataFrame(columns=columns_of(defect) + TEN_M_EXTRA)
    ca = _ca_rows(src)
    irc = src[src['threshold_name'].fillna('') == 'As per IRC']
    # IRC twin row of each CA row: same id with '_irc_' (NSV pairing), values as irc_* columns
    irc = pd.DataFrame({
        '_key': irc['id'].str.replace('_irc_', '_', regex=False).values,
        'irc_threshold_value': num(irc['threshold_value']).values,
        'irc_breach_flag': num(irc['breach_flag']).values,
        'irc_rating': irc['rating_irc'].values,
        'irc_road_condition': irc['road_condition'].values,
    }).drop_duplicates('_key')
    out = ca.assign(_key=ca['id']).merge(irc, on='_key', how='left').drop(columns='_key')

    out['ca_threshold_value'] = num(out['threshold_value'])
    out['ca_breach_flag'] = num(out['breach_flag'])
    out['ca_rating'] = out['rating_ca']
    out['ca_road_condition'] = out['road_condition']

    # one row = CA + IRC: breach if either standard breaches (blank when neither can be judged)
    bf = pd.concat([out['ca_breach_flag'], out['irc_breach_flag']], axis=1).max(axis=1, skipna=True)
    out['breach_flag'] = bf.astype('Int64')
    out['ca_breach_flag'] = out['ca_breach_flag'].astype('Int64')
    out['irc_breach_flag'] = out['irc_breach_flag'].astype('Int64')
    out['threshold_name'] = 'As per CA & IRC'
    seg = num(out['length_m']).fillna(num(out['total_length'])).fillna(0.0)
    out['affected_length'] = np.where(bf.eq(1).fillna(False), seg, 0.0)          # no threshold (NULL) → 0
    out['affected_length_irc'] = np.where(out['irc_breach_flag'].eq(1).fillna(False).astype(bool), seg, 0.0)
    out['reporting_interval_m'] = int(config.CHILD_10M)

    out['collection_name'] = table          # id is kept from master_<d>_child_10m (as the DLM notebook)
    out['level'] = 'child_10m'
    out['display_defect_id'] = None
    out = side_parent_cols(out, prj, block, by)
    if defect == 'cracking':
        out['measures'] = _crack_measures(out, 'child_10m')
    return to_columns(_sort_children(out), columns_of(defect) + TEN_M_EXTRA)


# ── child_100m_<d> (lane-wise 100 m, IRC only) ───────────────────────────────
def build_child_irc100(prj, defect, table=None, block=None, by='side'):
    """DLM build_child_irc100: 100 m rows with the IRC threshold. NSV already builds the IRC twin of every 100 m row
    (IRC threshold and operator from D2), so those rows are used as they are."""
    table = table or f'child_100m_{defect}'
    src_t = f'master_{defect}_child_100m'
    src = built_table(prj, src_t)
    if src is None or src.empty:
        return pd.DataFrame(columns=columns_of(defect))
    tn = src['threshold_name'].fillna('')
    ca, out = src[tn == 'As per CA'], src[tn == 'As per IRC'].copy()
    out['id'] = out['id'].str.replace(f'{src_t}_irc_', f'{table}_', regex=False)
    out['record_id'] = out['record_id'].str.replace(r'_irc$', '', regex=True)          # CA base row ids (DLM)
    out['source_defect_id'] = out['source_defect_id'].str.replace(r'_irc$', '', regex=True)
    bf = num(out['breach_flag'])
    # defect_id (DLM): breach rows → defect_id of the CA row, else record_id; non-breach → NULL
    ca_did = pd.Series(ca['defect_id'].values, index=ca['id'].values)
    pair = out['id'].str.replace(f'{table}_', f'{src_t}_', regex=False)
    did = pd.Series(pair.map(ca_did).values, index=out.index)
    out['defect_id'] = np.where(bf == 1, did.where(did.notna(), out['record_id']), None)
    seg = num(out['length_m']).fillna(num(out['total_length'])).fillna(0.0)
    out['affected_length'] = np.where(bf == 1, seg, 0.0)
    out['affected_length_irc'] = out['affected_length']
    out['affected_length_ca'] = 0.0
    out['road_condition'] = out['rating_irc'].where(out['rating_irc'].notna(),
                                                    pd.Series(np.where(bf == 1, 'Poor', 'Good'), index=out.index)
                                                    .where(bf.notna(), None))
    out['reporting_interval_m'] = int(config.CHILD_100M)
    out['collection_name'] = table
    out['level'] = 'child_100m'
    out['display_defect_id'] = None
    out = keep_rating(out, 'irc')                                  # IRC only → rating_ca NULL
    out = side_parent_cols(out, prj, block, by)
    if defect == 'cracking':
        out['measures'] = _crack_measures(out, 'child_100m')
    return to_columns(_sort_children(out), columns_of(defect))


# ── potholes: master_pothole (one row per pothole) ──
def _image_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple, np.ndarray)):
        return [str(x) for x in v if x is not None and str(x) not in ('', 'nan', 'None')]
    s = str(v)
    return [] if s in ('', 'nan', 'None') else [x.strip() for x in s.split(config.IMAGE_SEPARATOR) if x.strip()]


def _group_image_pairs(g):
    """(names, urls): every distinct NSV image name of the rows of a group with its path (NSV image logic)."""
    names, urls = [], []
    for _, r in g.iterrows():
        nm = _image_list(r.get('image_name'))
        ur = _image_list(r.get('image_urls'))
        for i, x in enumerate(nm):
            if x not in names:
                names.append(x)
                urls.append(ur[i] if i < len(ur) else x)
    return names, urls


def _group_images(g):
    """Every distinct NSV image name of the rows of a group, in row order (NSV logic: joined with
    config.IMAGE_SEPARATOR for image_name, the list for image_urls)."""
    imgs = []
    for _, r in g.iterrows():
        for x in (_image_list(r.get('image_urls')) or _image_list(r.get('image_name'))):
            if x not in imgs:
                imgs.append(x)
    return imgs


def build_pothole_records(prj):
    """master_pothole (dlm_kpi_new): ONE ROW PER POTHOLE (defect records), DLM pothole column list.
    Every value comes from the NSV pothole row (master_pothole in dlm_kpi, D4 NHAI One sheet): lane, chainage,
    lat / long, area, severity, breach (NSV severity rule), ratings (D4 Visual Condition), image names (NSV logic).
    Added: collection_name / level 'parent', side, LHS / RHS 1 km block (parent_start / end_chainage, parent_id),
    id {UPC}_master_pothole_{nnnnnn}; display_defect_id is set afterwards (breach rows, top-level numbers)."""
    table = 'master_pothole'
    src = built_table(prj, 'master_pothole')            # NSV lane-wise potholes (one row per pothole)
    if src is None or src.empty:
        return pd.DataFrame(columns=POTHOLE_COLUMNS)
    out = src.copy()
    out['collection_name'] = table
    out['level'] = 'parent'
    out['display_defect_id'] = None
    out['image_url'] = None
    out['total_children'] = 1
    out['segment_count'] = 1
    out = side_parent_cols(out, prj)
    out = _sort_children(out)
    out['id'] = [f"{prj.upc}_{table}_{i:06d}" for i in range(1, len(out) + 1)]
    return to_columns(out, POTHOLE_COLUMNS)


# ── display_defect_id for the hierarchy (DLM notebook) ───────────────────────
def table_name(key):
    """Output table name of a hierarchy key (new_master_pothole → master_pothole)."""
    return key[4:] if key.startswith('new_') else key

def assign_hierarchy_display_ids(prj, tables):
    """Parents: breach rows D/{ddmmyy}/N/{%05d} ordered by side, lane, start, id. Children: breach rows whose side
    parent has an id → {parent id}/{%04d} numbered inside the parent by lane, start, id; other breach rows (orphans)
    → their own D/{ddmmyy}/N/{%05d}. Non-breach rows NULL. The counter continues after the highest counter of OTHER
    UPCs in these tables (dlm_kpi_new) of the output folder. Returns {key: DataFrame}."""
    from common.display_ids import _max_counter_other_upcs
    keys = [t for p, cs in config.HIERARCHY_TABLES.items() for t in [p] + cs]
    work = {t: tables[t].copy() for t in keys if t in tables and tables[t] is not None and len(tables[t])}
    if not work:
        return {}
    date = prj.display_id_date_str
    n = _max_counter_other_upcs(prj, date, [table_name(k) for k in keys], folder=config.HIERARCHY_FOLDER)
    print(f"\nhierarchy display_defect_id: date {date} | existing max counter (other UPCs): {n}")

    def number_top(df, mask):
        nonlocal n
        sub = df.loc[mask].assign(_lk=df.loc[mask, 'lane'].map(_lane_key))
        idx = sub.sort_values(['side', '_lk', 'start_chainage', 'id'], na_position='last', kind='mergesort').index
        df.loc[idx, 'display_defect_id'] = [f"D/{date}/N/{n + i:05d}" for i in range(1, len(idx) + 1)]
        n += len(idx)

    for p in config.HIERARCHY_TABLES:                       # 1) every parent first
        if p in work:
            df = work[p]
            df['display_defect_id'] = None
            number_top(df, num(df['breach_flag']).eq(1).values)
    for p, children in config.HIERARCHY_TABLES.items():     # 2) children
        look = (work[p].dropna(subset=['display_defect_id']).set_index('parent_id')['display_defect_id']
                if p in work else pd.Series(dtype=object))
        for c in children:
            if c not in work:
                continue
            df = work[c]
            df['display_defect_id'] = None
            br = num(df['breach_flag']).eq(1).values
            pdid = df['parent_id'].map(look)
            has_p = br & pdid.notna().values
            if has_p.any():
                sub = df.loc[has_p].assign(_pdid=pdid[has_p], _lk=df.loc[has_p, 'lane'].map(_lane_key))
                sub = sub.sort_values(['parent_id', '_lk', 'start_chainage', 'id'], na_position='last', kind='mergesort')
                rn = sub.groupby('parent_id').cumcount() + 1
                df.loc[sub.index, 'display_defect_id'] = [f"{a}/{int(b):04d}" for a, b in zip(sub['_pdid'], rn)]
            orphan = br & pdid.isna().values
            number_top(df, orphan)
            print(f"  {c}: child ids {int(has_p.sum()):,} | orphan (own counter) {int(orphan.sum()):,}")
    return work
