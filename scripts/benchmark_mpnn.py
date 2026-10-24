"""Ablation benchmark: MPNN-LSTM (Panagopoulos et al., 2021) with a FIXED adjacency, on the rolling-origin rows.

Runs in the separate bench venv (plain torch, no torch_geometric; see requirements-bench.txt):
    %USERPROFILE%\\.venvs\\bantay-bench\\Scripts\\python scripts/benchmark_mpnn.py [--adjacency border_ferry|border|none]
    [--device cuda] [--seeds 3]

Graph (fixed, not learned): harmonised units that share a border (data/processed/units.gpkg in UTM 51N, each polygon
buffered by BUFFER_M, pairs that then intersect), plus units joined by a RoRo route (data/raw/roroph/roro_routes.rda,
read with rdata only; province names are GADM-style, matched by a normalised name with three explicit aliases:
Polillo -> Quezon, Samal -> Davao del Norte, Samar -> Samar (Western Samar); routes inside one unit are dropped). The
2024-2026 RoRo network is a proxy for 2018-2019 (see AGENTS.md). Normalised as D^-1/2 (A + I) D^-1/2.
--adjacency none uses the identity (no message passing) as the graph ablation.

Model: per week of a W-week input window, two graph-convolution layers (message passing over the fixed graph) on the
node features, their outputs concatenated with the raw features, an LSTM over the window per node, and an MLP head
that outputs 4 horizons x 23 quantiles (a base value plus cumulative softplus steps, so quantiles never cross), as a
residual on the last scaled value. Node features per week: y = log1p(incidence per 100k) (forward-filled, plus a
missing flag), CHIRPS 7-day rain, upstream river rain and its excess, gale hit, week-of-year sin/cos; head inputs: log
population and y(t+h-52) for h = 1..4 (known at t; flagged missing before 2017). Loss: pinball loss averaged over the 23 FluSight levels and the
4 horizons, masked where the target is missing.

Leak-free rolling origin, as forecast.rolling_origin: refit every 13 weeks at R (forecast.refit_dates); training
samples are origins whose target week is <= R (and <= MODEL_END), the per-unit scaling of y (mean / sd) and the
covariate z-scores are fitted on weeks <= R only, the number of epochs is chosen by early stopping on the last 13
training origins (targets still <= R) and the model is then refit on all training origins with that many epochs;
forecasts are made for origins in [R, next R). Every input at origin t is from weeks <= t. Fixed seeds (0..seeds-1);
the reported quantiles are the per-level mean over the seed ensemble (then sorted).

Writes data/processed/app/bench_mpnn_lstm.parquet / .json (adjacency border_ferry) or bench_mpnn_lstm_<adjacency>.*.
"""

import argparse
import re
import time

import numpy as np
import pandas as pd

import benchmark_common as B
from bantay import forecast as F

W = 12  # input window (weeks)
BUFFER_M = 500
ALIASES = {"polillo": "quezon", "samal": "davaodelnorte", "samar": "samarwesternsamar"}
DYN = ["y", "y_missing", "chirps_7d", "river_up_7d", "river_excess_7d", "storm_gale_hit", "woy_sin", "woy_cos"]
ZSCORE = ["chirps_7d", "river_up_7d", "river_excess_7d"]


def _norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower().replace("ñ", "n"))


def adjacency(units, kind):
    """Symmetric 0/1 adjacency over `units` (sorted ids) and a description of the edges."""
    import geopandas as gpd
    import rdata

    n = len(units)
    A = np.zeros((n, n))
    info = {}
    if kind == "none":
        return A, dict(n_border=0, n_ferry=0)
    u = gpd.read_file(B.C.PROCESSED / "units.gpkg").set_index("unit_id").loc[units].to_crs(B.C.CRS_M)
    buf = u.geometry.buffer(BUFFER_M)
    ix = {k: i for i, k in enumerate(units)}
    g = gpd.GeoDataFrame(geometry=buf.values)  # positional index = position in `units`
    sj = gpd.sjoin(g, g, predicate="intersects")
    for a, b in zip(sj.index, sj["index_right"]):
        if a != b:
            A[a, b] = 1
    info["n_border"] = int(A.sum() // 2)
    if kind == "border_ferry":
        rr = rdata.read_rda(B.C.RAW / "roroph" / "roro_routes.rda")["roro_routes"].reset_index(drop=True)
        name2id = {_norm(nm): uid for uid, nm in zip(u.index, u.unit_name)}

        def to_id(prov):
            k = _norm(prov)
            return name2id.get(ALIASES.get(k, k))

        a_id, b_id = rr.from_prov.map(to_id), rr.to_prov.map(to_id)
        info["ferry_unmatched"] = sorted(set(rr.from_prov[a_id.isna()]) | set(rr.to_prov[b_id.isna()]))
        # check the name match against the (coarse) port coordinates: nearest unit polygon to each port
        pts = lambda lat, lon: gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(B.C.CRS_M)
        near = lambda g: u.index[[int(np.argmin(u.geometry.distance(pt).to_numpy())) for pt in g]]
        agree = np.r_[near(pts(rr.from_lat, rr.from_lon)) == a_id.to_numpy(), near(pts(rr.to_lat, rr.to_lon)) == b_id.to_numpy()]
        info["ferry_port_coord_agreement"] = float(agree.mean())
        before = A.copy()
        n_intra = 0
        for a, b in zip(a_id, b_id):
            if a is None or b is None or pd.isna(a) or pd.isna(b):
                continue
            if a == b:
                n_intra += 1
                continue
            A[ix[a], ix[b]] = A[ix[b], ix[a]] = 1
        info.update(n_routes=len(rr), n_routes_intra_unit=n_intra, n_ferry_new_edges=int((A - before).sum() // 2))
    info["n_edges"] = int(A.sum() // 2)
    info["n_isolated"] = int((A.sum(1) == 0).sum())
    return A, info


def norm_adj(A):
    A = A + np.eye(len(A))
    d = 1 / np.sqrt(A.sum(1))
    return A * d[:, None] * d[None, :]


def arrays(p):
    """Wide (unit x week) arrays of the raw dynamic inputs; y forward-filled (past only) with a missing flag."""
    Y = B.wide(p, "y")
    out = {"y_raw": Y.to_numpy(float)}
    out["y"] = Y.ffill(axis=1).to_numpy(float)
    out["y_missing"] = Y.isna().to_numpy(float)
    for c in ZSCORE + ["storm_gale_hit"]:
        out[c] = B.wide(p, c).reindex(index=Y.index, columns=Y.columns).to_numpy(float)
    woy = Y.columns.isocalendar().week.to_numpy(int)
    out["woy_sin"] = np.broadcast_to(np.sin(2 * np.pi * woy / 52.18), Y.shape).copy()
    out["woy_cos"] = np.broadcast_to(np.cos(2 * np.pi * woy / 52.18), Y.shape).copy()
    out["log_pop"] = np.log(p.groupby("unit_id")["pop"].first().reindex(Y.index).to_numpy(float))
    return Y.index.tolist(), Y.columns, out


def build_tensors(arr, weeks, R):
    """Scale with statistics from weeks <= R only. Returns X (week, unit, n_dyn), Z (scaled y raw), static, lag52."""
    tr = weeks <= R
    yr = arr["y_raw"]
    mu = np.nanmean(yr[:, tr], axis=1)
    sd = np.nanstd(yr[:, tr], axis=1) + 0.1
    sc = lambda a: (a - mu[:, None]) / sd[:, None]
    feats = []
    for c in DYN:
        a = arr[c]
        if c == "y":
            a = np.nan_to_num(sc(a), nan=0.0)
        elif c in ZSCORE:
            m, s = np.nanmean(a[:, tr]), np.nanstd(a[:, tr]) + 1e-6
            a = np.nan_to_num((a - m) / s, nan=0.0)
        feats.append(np.nan_to_num(a, nan=0.0))
    X = np.stack(feats, -1).transpose(1, 0, 2)  # week, unit, feat
    Z = sc(yr).T  # week, unit (NaN where missing)
    lp = arr["log_pop"]
    static = ((lp - lp.mean()) / lp.std())[:, None]
    return X.astype(np.float32), Z.astype(np.float32), static.astype(np.float32), mu, sd


def make_net(torch, n_dyn, n_static, hidden=64, gcn=32, nq=23, nh=4, dropout=0.1):
    nn = torch.nn

    class MPNNLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.g1, self.g2 = nn.Linear(n_dyn, gcn), nn.Linear(gcn, gcn)
            self.lstm = nn.LSTM(n_dyn + 2 * gcn, hidden, num_layers=2, batch_first=True, dropout=dropout)
            self.head = nn.Sequential(nn.Linear(hidden + n_static + 2 * nh + n_dyn, hidden), nn.ReLU(), nn.Dropout(dropout),
                                      nn.Linear(hidden, nh * nq))
            self.nq, self.nh = nq, nh

        def forward(self, x, Ahat, static, lag):
            # x: (B, W, N, F); Ahat: (N, N); static: (N, S); lag: (B, N, 2*nh)
            b, w, n, f = x.shape
            h1 = torch.relu(torch.einsum("ij,bwjf->bwif", Ahat, self.g1(x)))
            h2 = torch.relu(torch.einsum("ij,bwjf->bwif", Ahat, self.g2(h1)))
            z = torch.cat([x, h1, h2], -1).permute(0, 2, 1, 3).reshape(b * n, w, -1)
            hT = self.lstm(z)[0][:, -1].reshape(b, n, -1)
            last = x[:, -1]
            o = self.head(torch.cat([hT, static.expand(b, n, -1), lag, last], -1)).reshape(b, n, self.nh, self.nq)
            base = o[..., :1]
            steps = torch.nn.functional.softplus(o[..., 1:]) + 1e-4
            mid = (len(B.Q) - 1) // 2
            q = torch.cat([base, base + torch.cumsum(steps, -1)], -1)
            q = q - q[..., mid:mid + 1] + base  # base is the median
            return last[..., :1].unsqueeze(-1) + q  # residual on the last scaled y (feature 0)

    return MPNNLSTM()


def samples(X, Z, idx):
    """For origin week indices idx: input windows, seasonal lags y(t+h-52) (+ missing flags), targets (B, N, 4)."""
    xs = np.stack([X[i - W + 1: i + 1] for i in idx])
    nan = np.full(Z.shape[1], np.nan, dtype=Z.dtype)
    lag = np.stack([np.stack([Z[i + h - 52] if i + h >= 52 else nan for h in B.HORIZONS], -1) for i in idx])  # (B, N, 4)
    lagf = np.isnan(lag).astype(np.float32)
    tgt = np.stack([np.stack([Z[i + h] if i + h < len(Z) else np.full(Z.shape[1], np.nan) for h in B.HORIZONS], -1)
                    for i in idx])
    return xs, np.concatenate([np.nan_to_num(lag, nan=0.0), lagf], -1).astype(np.float32), tgt.astype(np.float32)


def pinball(torch, q, y, levels):
    m = ~torch.isnan(y)
    yy = torch.nan_to_num(y)[..., None]
    e = yy - q
    loss = torch.maximum(levels * e, (levels - 1) * e).mean(-1)
    return (loss * m).sum() / m.sum().clamp(min=1)


def train(torch, net, data, Ahat, static, epochs, device, seed, val=None, batch=16, lr=1e-3, patience=25):
    """Adam on mini-batches of weekly graph snapshots. With `val`, returns the best epoch (early stopping)."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    levels = torch.tensor(B.Q, dtype=torch.float32, device=device)
    xs, lag, tgt = (torch.tensor(a, device=device) for a in data)
    best, best_ep, bad = np.inf, 1, 0
    for ep in range(1, epochs + 1):
        net.train()
        for b in np.array_split(rng.permutation(len(xs)), max(1, len(xs) // batch)):
            opt.zero_grad()
            loss = pinball(torch, net(xs[b], Ahat, static, lag[b]), tgt[b], levels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
        if val is not None:
            net.eval()
            with torch.no_grad():
                vx, vl, vt = (torch.tensor(a, device=device) for a in val)
                v = float(pinball(torch, net(vx, Ahat, static, vl), vt, levels))
            if v < best - 1e-4:
                best, best_ep, bad = v, ep, 0
            else:
                bad += 1
                if bad >= patience:
                    break
    return best_ep


def main(kind, device, n_seeds, max_epochs):
    import torch

    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    t0 = time.time()
    rows = B.eval_rows()
    p = B.panel()
    units, weeks, arr = arrays(p)
    A, ainfo = adjacency(units, kind)
    print(f"  adjacency {kind}: {ainfo}")
    Ahat = torch.tensor(norm_adj(A), dtype=torch.float32, device=device)
    end = pd.Timestamp(B.C.MODEL_END)
    refits = F.refit_dates("2018-01-07", B.C.MODEL_END, 13)
    first = W - 1  # first origin with a full input window (y(t+h-52) is flagged missing in the first year)
    wk = np.asarray(weeks)
    out, log = [], []
    for k, R in enumerate(refits):
        nxt = refits[k + 1] if k + 1 < len(refits) else end + pd.Timedelta(weeks=1)
        X, Z, static, mu, sd = build_tensors(arr, weeks, R)
        st = torch.tensor(static, device=device)
        iR = int(np.flatnonzero(wk == R)[0])
        Zt = Z.copy()
        Zt[min(iR, int(np.flatnonzero(wk <= end)[-1])) + 1:] = np.nan  # no training target after R (or MODEL_END)
        tr_idx = np.arange(first, iR)  # origins t < R: targets t+h, masked when > R
        va_idx, fit_idx = tr_idx[-13:], tr_idx[:-13]
        test_idx = np.flatnonzero((wk >= R) & (wk < nxt) & (wk <= end))
        qsum = None
        eps = []
        for seed in range(n_seeds):
            torch.manual_seed(seed)
            net = make_net(torch, X.shape[-1], static.shape[-1]).to(device)
            ep = train(torch, net, samples(X, Zt, fit_idx), Ahat, st, max_epochs, device, seed, val=samples(X, Zt, va_idx))
            torch.manual_seed(seed)
            net = make_net(torch, X.shape[-1], static.shape[-1]).to(device)
            train(torch, net, samples(X, Zt, tr_idx), Ahat, st, ep, device, seed)
            net.eval()
            xs, lag, _ = samples(X, Z, test_idx)  # inputs only (weeks <= origin); targets unused
            with torch.no_grad():
                q = net(torch.tensor(xs, device=device), Ahat, st, torch.tensor(lag, device=device)).cpu().numpy()
            qsum = q if qsum is None else qsum + q
            eps.append(ep)
        q = np.sort(qsum / n_seeds, axis=-1)  # (B, N, 4, 23) scaled
        qlog = mu[None, :, None, None] + sd[None, :, None, None] * q
        for bi, i in enumerate(test_idx):
            for ni, u in enumerate(units):
                for h in B.HORIZONS:
                    out.append((u, wk[i], h, qlog[bi, ni, h - 1]))
        log.append(dict(refit=str(R.date()), n_train_origins=len(tr_idx), epochs_per_seed=eps, n_test_origins=len(test_idx)))
        print(f"  refit {R.date()}: {len(tr_idx)} training origins, epochs {eps}, {len(test_idx)} test origins "
              f"({time.time() - t0:.0f} s)", flush=True)
    fc = pd.DataFrame(out, columns=["unit_id", "week", "horizon", "q"])
    fc = fc.merge(rows[B.KEY], on=B.KEY)  # keep the evaluation rows (target week <= MODEL_END)
    name = "mpnn_lstm" if kind == "border_ferry" else f"mpnn_lstm_{kind}"
    runtime = time.time() - t0
    res = B.write_bench(name, fc, dict(
        packages=B.versions("torch", "numpy", "pandas", "geopandas", "rdata"),
        device=B.device_info(device), runtime_s=round(runtime, 1),
        adjacency=dict(kind=kind, buffer_m=BUFFER_M, aliases=ALIASES, **ainfo,
                       note="RoRo routes are 2024-2026 operations, a proxy for 2018-2019"),
        architecture=dict(window_weeks=W, gcn_layers=2, gcn_dim=32, lstm_layers=2, lstm_hidden=64, dropout=0.1,
                          output="4 horizons x 23 quantiles, monotone by construction, residual on last scaled y"),
        inputs=dict(dynamic=DYN, head=["log_pop (z)", "y(t+h-52) scaled, h=1..4, + missing flags", "last-week inputs"]),
        context=f"{W}-week window of node features ending at the origin week (weeks <= origin only)",
        covariates=["chirps_7d", "river_up_7d", "river_excess_7d", "storm_gale_hit"],
        training=dict(loss="pinball, mean over 23 levels and 4 horizons, masked NaN targets", optimiser="Adam lr 1e-3 wd 1e-4",
                      batch_snapshots=16, max_epochs=max_epochs, early_stopping="last 13 training origins, patience 25",
                      refit_weeks=13, seeds=list(range(n_seeds)), ensemble="mean of quantiles over seeds, then sorted",
                      scaling="per-unit mean/sd of y and global z-scores of rain/river fitted on weeks <= refit date"),
        quantile_interpolation="none: the network outputs the 23 FluSight levels",
        leakage="training targets <= refit date (and <= MODEL_END); scaling in-window; inputs at origin t use weeks <= t",
        refits=log))
    B.quick_score(res, name)
    print(f"  done in {runtime:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjacency", default="border_ferry", choices=["border_ferry", "border", "none"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--max-epochs", type=int, default=300)
    a = ap.parse_args()
    main(a.adjacency, a.device, a.seeds, a.max_epochs)
