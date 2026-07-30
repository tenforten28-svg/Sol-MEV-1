import { useEffect, useState } from "react";
import axios from "axios";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const Stat = ({ label, value, sub, testId }) => (
  <div
    data-testid={testId}
    className="bg-slate-900/60 border border-slate-800 rounded-lg p-3"
  >
    <div className="text-[10px] uppercase tracking-widest text-slate-400">{label}</div>
    <div className="text-lg font-semibold text-white mt-1">{value}</div>
    {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
  </div>
);

const shortMint = (m) => (m ? `${m.slice(0, 4)}…${m.slice(-4)}` : "—");
const shortSig = (s) => (s ? `${s.slice(0, 6)}…${s.slice(-6)}` : "—");

export default function PumpfunPanel() {
  const [status, setStatus] = useState(null);       // sniper status
  const [autobuy, setAutobuy] = useState(null);     // autobuy status
  const [detections, setDetections] = useState([]);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const refresh = async () => {
    try {
      const [s, ab, d, p] = await Promise.all([
        axios.get(`${BACKEND_URL}/api/live/pumpfun/status`),
        axios.get(`${BACKEND_URL}/api/live/pumpfun/autobuy_status`),
        axios.get(`${BACKEND_URL}/api/live/pumpfun/detections?limit=20`),
        axios.get(`${BACKEND_URL}/api/live/pumpfun/positions?limit=20`),
      ]);
      setStatus(s.data);
      setAutobuy(ab.data);
      setDetections(d.data?.detections || []);
      setPositions(p.data?.events || []);
      setErr(null);
    } catch (e) {
      setErr(e?.message || "fetch failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, []);

  const sniperOn = status?.enabled && status?.running;
  const autoOn = autobuy?.enabled;
  const cfg = autobuy?.config || {};

  return (
    <Card
      data-testid="pumpfun-panel"
      className="bg-gradient-to-br from-fuchsia-950/40 via-slate-900 to-slate-900 border-fuchsia-500/40 p-6 mb-6"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2
              data-testid="pumpfun-panel-title"
              className="text-xl font-bold text-white"
            >
              Pump.fun Sniper
            </h2>
            <Badge
              data-testid="pumpfun-sniper-badge"
              className={
                sniperOn
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                  : "bg-slate-700/40 text-slate-300 border-slate-600/40"
              }
            >
              Detector: {sniperOn ? "LIVE" : "OFF"}
            </Badge>
            <Badge
              data-testid="pumpfun-autobuy-badge"
              className={
                autoOn
                  ? "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40"
                  : "bg-slate-700/40 text-slate-300 border-slate-600/40"
              }
            >
              Auto-Buy: {autoOn ? "ARMED" : "SAFE"}
            </Badge>
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Direct bonding-curve execution via PumpPortal Local API + your QuickNode RPC.
            Your wallet key never leaves the server.
          </div>
        </div>
        {err && (
          <Badge
            data-testid="pumpfun-error-badge"
            className="bg-red-500/20 text-red-300 border-red-500/40"
          >
            {err}
          </Badge>
        )}
      </div>

      {loading && !status && (
        <div data-testid="pumpfun-loading" className="text-slate-400 text-sm">
          Loading…
        </div>
      )}

      {/* Counters */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-5">
        <Stat
          testId="pumpfun-stat-detections"
          label="Detections"
          value={status?.new_mint_detections ?? 0}
          sub={status?.last_detection_at ? new Date(status.last_detection_at).toLocaleTimeString() : "none"}
        />
        <Stat
          testId="pumpfun-stat-events"
          label="WSS Events"
          value={status?.total_events_received ?? 0}
          sub={status?.wss_host || "no wss"}
        />
        <Stat
          testId="pumpfun-stat-attempts"
          label="Buy Attempts"
          value={autobuy?.counters?.attempts ?? 0}
          sub={`safety rejects: ${autobuy?.counters?.rejects_safety ?? 0}`}
        />
        <Stat
          testId="pumpfun-stat-buys"
          label="Buys OK / Fired"
          value={`${autobuy?.counters?.buys_successful ?? 0} / ${autobuy?.counters?.buys_fired ?? 0}`}
          sub={`sells: ${autobuy?.counters?.sells_fired ?? 0}`}
        />
        <Stat
          testId="pumpfun-stat-positions"
          label="Open Positions"
          value={autobuy?.open_positions ?? 0}
          sub={`max ${cfg.max_concurrent ?? "—"}`}
        />
        <Stat
          testId="pumpfun-stat-budget"
          label="Daily Budget SOL"
          value={`${(autobuy?.day_budget_remaining_sol ?? 0).toFixed(4)}`}
          sub={`of ${cfg.daily_budget_sol ?? "—"} left`}
        />
      </div>

      {/* Config strip */}
      <div className="text-[11px] text-slate-400 bg-slate-900/60 border border-slate-800 rounded-md p-3 mb-5">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <div>Buy: <span className="text-fuchsia-300">{cfg.buy_sol ?? "—"} SOL</span></div>
          <div>Slippage: <span className="text-fuchsia-300">{cfg.slippage_pct ?? "—"}%</span></div>
          <div>Max dev hold: <span className="text-fuchsia-300">{cfg.max_dev_hold_pct ?? "—"}%</span></div>
          <div>Priority fee: <span className="text-fuchsia-300">{cfg.priority_fee_sol ?? "—"} SOL</span></div>
          <div>Hold max: <span className="text-fuchsia-300">{cfg.hold_max_seconds ?? "—"}s</span></div>
          <div>TP/SL: <span className="text-slate-400">advisory ({cfg.take_profit_mult ?? "—"}x / {cfg.stop_loss_mult ?? "—"}x, time-limit only)</span></div>
        </div>
        {autobuy?.last_reason && (
          <div className="mt-2 text-slate-500">
            last decision: <span className="text-slate-300">{autobuy.last_reason}</span>
          </div>
        )}
      </div>

      {/* Detections */}
      <div className="mb-5">
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
          Recent New Mints
        </div>
        <div
          data-testid="pumpfun-detections-list"
          className="max-h-64 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800"
        >
          {detections.length === 0 && (
            <div className="text-slate-500 text-sm p-3">
              No detections yet.{" "}
              {sniperOn ? "Waiting for new mints…" : "Detector is OFF."}
            </div>
          )}
          {detections.map((d, i) => (
            <div
              key={i}
              data-testid={`pumpfun-detection-${i}`}
              className="flex items-center justify-between p-2 text-xs"
            >
              <div className="flex flex-col">
                <span className="text-white font-mono">
                  {shortMint(d.candidate_mint)}
                </span>
                <span className="text-slate-500">
                  {d.detected_at ? new Date(d.detected_at).toLocaleTimeString() : ""}
                </span>
              </div>
              <div className="flex gap-2">
                {d.pumpfun_url && (
                  <a
                    href={d.pumpfun_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-fuchsia-300 hover:underline"
                    data-testid={`pumpfun-detection-link-${i}`}
                  >
                    pump.fun
                  </a>
                )}
                {d.solscan_url && (
                  <a
                    href={d.solscan_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-300 hover:underline"
                  >
                    tx
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Positions / Events */}
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
          Position Events
        </div>
        <div
          data-testid="pumpfun-positions-list"
          className="max-h-64 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800"
        >
          {positions.length === 0 && (
            <div className="text-slate-500 text-sm p-3">
              No positions yet.
            </div>
          )}
          {positions.map((p, i) => (
            <div
              key={i}
              data-testid={`pumpfun-position-${i}`}
              className="p-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge
                    className={
                      p.event === "opened"
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : p.event === "closed"
                        ? "bg-blue-500/20 text-blue-300 border-blue-500/40"
                        : p.event === "rejected"
                        ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                        : "bg-red-500/20 text-red-300 border-red-500/40"
                    }
                  >
                    {p.event}
                  </Badge>
                  <span className="text-white font-mono">{shortMint(p.mint)}</span>
                </div>
                <span className="text-slate-500">
                  {p.at ? new Date(p.at).toLocaleTimeString() : ""}
                </span>
              </div>
              <div className="mt-1 text-slate-400 flex flex-wrap gap-x-3">
                {p.verdict && <span>verdict: <span className="text-slate-200">{p.verdict}</span></span>}
                {p.buy_sol != null && <span>buy: {p.buy_sol} SOL</span>}
                {p.dev?.dev_hold_pct != null && (
                  <span>
                    dev holds:{" "}
                    <span className={p.dev.within_limit ? "text-emerald-300" : "text-red-300"}>
                      {p.dev.dev_hold_pct}%
                    </span>
                  </span>
                )}
                {p.hold_seconds != null && <span>held: {Math.round(p.hold_seconds)}s</span>}
                {p.reason && <span className="text-amber-300">{p.reason}</span>}
                {p.solscan_url && (
                  <a
                    href={p.solscan_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-300 hover:underline"
                  >
                    buy tx
                  </a>
                )}
                {p.solscan_sell && (
                  <a
                    href={p.solscan_sell}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-300 hover:underline"
                  >
                    sell tx
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="text-[10px] text-slate-500 mt-4">
        Signatures are shortened. Click through to Solscan/pump.fun for the full receipt.
        {" "}Note: PumpPortal is a third-party tx-builder; keys and submission stay on your server.
      </div>
    </Card>
  );
}
