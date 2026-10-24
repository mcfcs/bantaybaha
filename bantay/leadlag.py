"""Layer 2: lead-lag outbreak graph (PCMCI+), the lagged cross-correlation baseline, sentinels and communities.

Series: log1p(incidence), seasonally differenced (52 weeks) so a shared rainy-season peak does not make links, then
standardised. Everything is fit inside the training window passed in (no leakage). Lagged edges i -> j at lag 1-3
weeks are kept when PCMCI+ orients them and their Benjamini-Hochberg q-value is < alpha (on pure-noise checks with 85
series this removes the ~60-90 spurious edges PCMCI+ alone returns at pc_alpha = 0.01). Optional block bootstrap
gives a confidence (link frequency) per edge. PageRank on the reversed graph scores sentinels (provinces whose rises
are followed by others); Louvain on the undirected graph groups provinces that move together.
"""

import numpy as np
import pandas as pd
import networkx as nx
from scipy import stats

TAU_MAX = 3
MIN_T = 52  # weeks of differenced data needed to learn a graph (the earliest rolling-origin window has T = 53); a
            # shorter window (training ends in 2017: the catalogue's early storms) gets an empty graph
EDGE_COLS = ["source", "target", "lag", "weight", "q", "method", "confidence"]


def prepare(panel, end, value="incidence"):
    """(week x unit) standardised, seasonally differenced log incidence for weeks <= end."""
    x = panel[panel.week <= end].pivot(index="week", columns="unit_id", values=value)
    lx = np.log1p(x)
    d = (lx - lx.shift(52)).iloc[52:]
    d = d.loc[:, d.isna().mean() <= 0.1]  # units with many missing weeks (e.g. Davao Occidental) sit out the graph
    d = d.interpolate(limit=4, limit_direction="both")  # short gaps only
    d = d.dropna(axis=0, how="any")
    sd = d.std().replace(0, np.nan)
    return ((d - d.mean()) / sd).dropna(axis=1)


def _bh(p):
    q = np.full(p.shape, np.nan)
    ok = ~np.isnan(p)
    if ok.any():
        from scipy.stats import false_discovery_control

        q[ok] = false_discovery_control(p[ok], method="bh")
    return q


def xcorr_graph(d, tau_max=TAU_MAX, alpha=0.05):
    """Baseline: positive lagged Pearson correlation d_i(t-l) -> d_j(t), best lag per pair, BH-corrected."""
    z = d.to_numpy()
    T, n = z.shape
    rows = []
    for lag in range(1, tau_max + 1):
        a, b = z[:-lag], z[lag:]
        a = (a - a.mean(0)) / a.std(0)
        b = (b - b.mean(0)) / b.std(0)
        r = a.T @ b / (T - lag)
        t = r * np.sqrt((T - lag - 2) / np.clip(1 - r ** 2, 1e-12, None))
        p = 2 * stats.t.sf(np.abs(t), T - lag - 2)
        ii, jj = np.nonzero(~np.eye(n, dtype=bool))
        rows.append(pd.DataFrame({"i": ii, "j": jj, "lag": lag, "val": r[ii, jj], "p": p[ii, jj]}))
    e = pd.concat(rows)
    e["q"] = _bh(e.p.to_numpy())
    e = e[(e.q < alpha) & (e.val > 0)].sort_values("val", ascending=False).drop_duplicates(["i", "j"])
    cols = d.columns.to_numpy()
    return pd.DataFrame({"source": cols[e.i], "target": cols[e.j], "lag": e.lag.values, "weight": e.val.values,
                         "q": e.q.values, "method": "xcorr"})


def pcmci_graph(d, tau_max=TAU_MAX, pc_alpha=0.01, alpha=0.05, boot=0, seed=0):
    """PCMCI+ (ParCorr) lagged edges with BH q < alpha; `boot` > 0 adds bootstrap link frequency as `confidence`."""
    from tigramite import data_processing as pp
    from tigramite.pcmci import PCMCI
    from tigramite.independence_tests.parcorr import ParCorr

    args = dict(tau_min=0, tau_max=tau_max, pc_alpha=pc_alpha, max_conds_dim=2, max_conds_px=2, max_conds_py=2)
    pc = PCMCI(dataframe=pp.DataFrame(d.to_numpy()), cond_ind_test=ParCorr(significance="analytic"), verbosity=0)
    r = pc.run_pcmciplus(**args)
    q = pc.get_corrected_pvalues(p_matrix=r["p_matrix"], fdr_method="fdr_bh", exclude_contemporaneous=False)
    g, val = r["graph"], r["val_matrix"]
    ii, jj, ll = np.nonzero((g == "-->") & (q < alpha))
    keep = (ll >= 1) & (ii != jj)  # lead-lag between provinces only: no contemporaneous links, no own-autocorrelation
    ii, jj, ll = ii[keep], jj[keep], ll[keep]
    cols = d.columns.to_numpy()
    e = pd.DataFrame({"source": cols[ii], "target": cols[jj], "lag": ll, "weight": val[ii, jj, ll], "q": q[ii, jj, ll],
                      "method": "pcmciplus"})
    if boot and len(e):
        b = pc.run_bootstrap_of(method="run_pcmciplus", method_args=args, boot_samples=boot,
                                boot_blocklength=max(2, tau_max), seed=seed)
        freq = b["summary_results"]["link_frequency"]
        e["confidence"] = freq[ii, jj, ll]
    else:
        e["confidence"] = np.nan
    # strongest lag per ordered pair
    return e.reindex(e.weight.abs().sort_values(ascending=False).index).drop_duplicates(["source", "target"])


def node_metrics(edges, nodes, seed=0):
    """PageRank sentinel score, out/in degree and Louvain community per unit."""
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    for s, t, w in zip(edges.source, edges.target, edges.weight.abs()):
        G.add_edge(s, t, weight=float(w))
    pr = nx.pagerank(G.reverse(), weight="weight") if G.number_of_edges() else {n: 1 / len(nodes) for n in nodes}
    comms = nx.community.louvain_communities(G.to_undirected(), weight="weight", seed=seed) if G.number_of_edges() else [{n} for n in nodes]
    comm = {n: k for k, c in enumerate(sorted(comms, key=len, reverse=True)) for n in c}
    m = pd.DataFrame({"unit_id": list(nodes)})
    m["sentinel_score"] = m.unit_id.map(pr)
    m["out_degree"] = m.unit_id.map(dict(G.out_degree()))
    m["in_degree"] = m.unit_id.map(dict(G.in_degree()))
    m["community"] = m.unit_id.map(comm)
    m["sentinel_rank"] = m.sentinel_score.rank(ascending=False, method="first").astype(int)
    m["is_sentinel"] = (m.out_degree > 0) & (m.sentinel_rank <= max(5, len(nodes) // 10))
    return m


def learn(panel, end, method="pcmciplus", boot=0):
    """Edges + node metrics for the training window ending at `end`."""
    d = prepare(panel, end)
    if len(d) < MIN_T:
        edges = pd.DataFrame({c: pd.Series(dtype=float if c in ("weight", "q", "confidence") else object) for c in EDGE_COLS})
    else:
        edges = pcmci_graph(d, boot=boot) if method == "pcmciplus" else xcorr_graph(d)
    nodes = sorted(panel.unit_id.unique())
    m = node_metrics(edges, nodes)
    meta = dict(end=str(pd.Timestamp(end).date()), method=method, T=len(d), n_series=d.shape[1], n_edges=len(edges))
    return edges.assign(window_end=meta["end"]), m.assign(window_end=meta["end"], method=method), meta
