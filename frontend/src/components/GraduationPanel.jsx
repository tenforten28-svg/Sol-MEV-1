import { useEffect, useState } from "react";
import axios from "axios";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

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
const fmtSol = (n) => (typeof n === "number" ? n.toFixed(4) : "—");

export default function GraduationPanel() {
  const [state, setState] = useState({ monitor: null, executor: null });
  const [events, setEvents] = useState([]);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const [stopMsg, setStopMsg] = useState(null);

  const refresh = async () => {
    try {
      const [st, ev, po] = await Promise.all([
        axios.get(`${BACKEND_URL}/api/live/graduation/status`),
        axios.get(`${BACKEND_URL}/api/live/graduation/events?limit=15`),
        axios.get(`${BACKEND_URL}/api/live/graduation/positions?limit=20`),
      ]);
      setState({ monitor: st.data?.monitor, executor: st.data?.executor });
      setEvents(ev.data?.events || []);
      setPositions(po.data?.events || []);
      setErr(null);
    } catch (e) {
      setErr(e?.message || "fetch failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 6000);
    return () => clearInterval(id);
  }, []);

  const emergencyStop = async () => {
    if (!window.confirm("Kill switch — disables live trader + pump.fun autobuy + graduation executor in-process. Continue?")) return;
    try {
      const r = await axios.post(`${BACKEND_URL}/api/live/emergency_stop`);
      setStopMsg(`stopped: ${(r.data?.stopped || []).join(", ")}`);
      refresh();
    } catch (e) {
      setStopMsg(`error: ${e?.message}`);
    }
  };

  const mon = state.monitor;
  const exe = state.executor;
  const cfg = exe?.config || {};
  const cnt = exe?.counters || {};
  const monRunning = mon?.enabled && mon?.running;
  const exeArmed = exe?.enabled;

  return (
    <Card
      data-testid="graduation-panel"
      className="bg-gradient-to-br from-cyan-950/40 via-slate-900 to-slate-900 border-cyan-500/40 p-6 mb-6"
    >
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h2 data-testid="graduation-panel-title" className="text-xl font-bold text-white">
              Graduation Sniper
            </h2>
            <Badge
              data-testid="graduation-monitor-badge"
              className={
                monRunning
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                  : "bg-slate-700/40 text-slate-300 border-slate-600/40"
              }
            >
              Monitor: {monRunning ? "LIVE" : "OFF"}
            </Badge>
            <Badge
              data-testid="graduation-executor-badge"
              className={
                exeArmed
                  ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                  : "bg-slate-700/40 text-slate-300 border-slate-600/40"
              }
            >
              Executor: {exeArmed ? "ARMED" : "SAFE"}
            </Badge>
            <Badge className="bg-slate-800/60 text-slate-300 border-slate-600/40">
              Strategy: {exe?.strategy || "—"}
            </Badge>
          </div>
          <div className="text-xs text-slate-400 mt-1">
            PumpSwap + Raydium CPMM (LaunchLab). Fade-the-dump: settle {cfg.settle_delay_sec ?? "—"}s,
            then Jupiter-route buy with real TP/SL.
          </div>
        </div>
        <div className="flex items-center gap-2">
          {err && (
            <Badge className="bg-red-500/20 text-red-300 border-red-500/40">
              {err}
            </Badge>
          )}
          <Button
            data-testid="graduation-emergency-stop"
            onClick={emergencyStop}
            variant="destructive"
            className="bg-red-600 hover:bg-red-500 text-white"
          >
            Emergency Stop
          </Button>
        </div>
      </div>

      {stopMsg && (
        <div data-testid="graduation-stop-msg" className="mb-3 text-xs text-amber-300">
          {stopMsg}
        </div>
      )}

      {loading && !mon && (
        <div data-testid="graduation-loading" className="text-slate-400 text-sm">Loading…</div>
      )}

      {/* Per-source health */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-5">
        <Stat
          testId="graduation-stat-pumpswap-detections"
          label="PumpSwap ✓"
          value={mon?.pumpswap?.graduations_detected ?? 0}
          sub={`${mon?.pumpswap?.events_received ?? 0} events`}
        />
        <Stat
          testId="graduation-stat-bonk-detections"
          label="Bonk/CPMM ✓"
          value={mon?.bonk_cpmm?.graduations_detected ?? 0}
          sub={`${mon?.bonk_cpmm?.events_received ?? 0} events`}
        />
        <Stat
          testId="graduation-stat-events-seen"
          label="Events Seen"
          value={cnt.events_seen ?? 0}
          sub={`filter rejects: ${cnt.rejects_filter ?? 0}`}
        />
        <Stat
          testId="graduation-stat-buys"
          label="Buys OK / Fired"
          value={`${cnt.buys_successful ?? 0} / ${cnt.buys_fired ?? 0}`}
          sub={`sells: ${cnt.sells_fired ?? 0}`}
        />
        <Stat
          testId="graduation-stat-positions"
          label="Open Positions"
          value={exe?.open_positions ?? 0}
          sub={`max ${cfg.max_concurrent ?? "—"}`}
        />
        <Stat
          testId="graduation-stat-budget"
          label="Daily Budget SOL"
          value={fmtSol(exe?.day_budget_remaining_sol ?? 0)}
          sub={`of ${cfg.daily_budget_sol ?? "—"} left`}
        />
      </div>

      {/* Config strip */}
      <div className="text-[11px] text-slate-400 bg-slate-900/60 border border-slate-800 rounded-md p-3 mb-5">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
          <div>Buy: <span className="text-cyan-300">{cfg.buy_sol ?? "—"} SOL</span></div>
          <div>Settle: <span className="text-cyan-300">{cfg.settle_delay_sec ?? "—"}s</span></div>
          <div>Slippage: <span className="text-cyan-300">{cfg.slippage_bps ? `${cfg.slippage_bps / 100}%` : "—"}</span></div>
          <div>Min pool: <span className="text-cyan-300">{cfg.min_pool_sol ?? "—"} SOL</span></div>
          <div>Hold max: <span className="text-cyan-300">{cfg.hold_max_seconds ?? "—"}s</span></div>
          <div data-testid="graduation-cfg-ladder">Ladder: <span className="text-emerald-300">{(cfg.ladder || []).map(m => `${m.mult}x→${m.sell_pct}%→floor${m.floor_after}x`).join(" | ") || "—"}</span></div>
          <div data-testid="graduation-cfg-rugstop">Rug stop: <span className="text-red-300">{cfg.rug_stop_mult ?? "—"}x</span></div>
          <div>PumpSwap: <span className={cfg.pumpswap_enabled ? "text-emerald-300" : "text-slate-500"}>{cfg.pumpswap_enabled ? "on" : "off"}</span></div>
          <div>Bonk: <span className={cfg.bonk_enabled ? "text-emerald-300" : "text-slate-500"}>{cfg.bonk_enabled ? "on" : "off"}</span></div>
        </div>
        {exe?.last_reason && (
          <div className="mt-2 text-slate-500">
            last decision: <span className="text-slate-300">{exe.last_reason}</span>
          </div>
        )}
      </div>

      {/* Detected graduations */}
      <div className="mb-5">
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
          Recent Graduations
        </div>
        <div
          data-testid="graduation-events-list"
          className="max-h-64 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800"
        >
          {events.length === 0 && (
            <div className="text-slate-500 text-sm p-3">
              No graduations yet. {monRunning ? "Watching…" : "Monitor OFF."}
            </div>
          )}
          {events.map((e, i) => (
            <div
              key={i}
              data-testid={`graduation-event-${i}`}
              className="flex items-center justify-between p-2 text-xs"
            >
              <div className="flex items-center gap-2">
                <Badge
                  className={
                    e.source === "pumpswap"
                      ? "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40"
                      : "bg-orange-500/20 text-orange-300 border-orange-500/40"
                  }
                >
                  {e.source === "pumpswap" ? "PumpSwap" : "Bonk"}
                </Badge>
                <span className="text-white font-mono">{shortMint(e.mint)}</span>
                <span className="text-slate-400">{fmtSol(e.reserves_sol)} SOL</span>
                {e.latency_ms != null && (
                  <span className="text-slate-500">Δ{e.latency_ms}ms</span>
                )}
              </div>
              <div className="flex gap-2">
                <span className="text-slate-500">
                  {e.detected_at ? new Date(e.detected_at).toLocaleTimeString() : ""}
                </span>
                {e.solscan_url && (
                  <a
                    href={e.solscan_url}
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

      {/* Positions */}
      <div>
        <div className="text-xs uppercase tracking-widest text-slate-400 mb-2">
          Position Events
        </div>
        <div
          data-testid="graduation-positions-list"
          className="max-h-64 overflow-auto border border-slate-800 rounded-md divide-y divide-slate-800"
        >
          {positions.length === 0 && (
            <div className="text-slate-500 text-sm p-3">No positions yet.</div>
          )}
          {positions.map((p, i) => (
            <div key={i} data-testid={`graduation-position-${i}`} className="p-2 text-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge
                    className={
                      p.event === "opened"
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : p.event === "partial_sell"
                        ? "bg-purple-500/20 text-purple-300 border-purple-500/40"
                        : p.event === "closed"
                        ? (p.pnl_sol > 0
                            ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                            : "bg-blue-500/20 text-blue-300 border-blue-500/40")
                        : p.event === "rejected"
                        ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                        : "bg-red-500/20 text-red-300 border-red-500/40"
                    }
                  >
                    {p.event}
                  </Badge>
                  <span className="text-white font-mono">{shortMint(p.mint)}</span>
                  {p.source && <span className="text-slate-500">{p.source}</span>}
                </div>
                <span className="text-slate-500">
                  {p.at ? new Date(p.at).toLocaleTimeString() : ""}
                </span>
              </div>
              <div className="mt-1 text-slate-400 flex flex-wrap gap-x-3">
                {p.verdict && <span>verdict: <span className="text-slate-200">{p.verdict}</span></span>}
                {p.reason && p.event === "partial_sell" && <span className="text-purple-300">{p.reason}</span>}
                {p.ratio != null && <span>ratio: <span className="text-emerald-300">{p.ratio}x</span></span>}
                {p.peak_ratio != null && <span>peak: <span className="text-amber-300">{p.peak_ratio}x</span></span>}
                {p.current_floor != null && <span>floor: {p.current_floor}x</span>}
                {p.sell_pct_of_current != null && <span>sold: {p.sell_pct_of_current}%</span>}
                {p.buy_sol != null && <span>buy: {p.buy_sol} SOL</span>}
                {p.sell_sol_received != null && <span>total sold: {p.sell_sol_received} SOL</span>}
                {p.pnl_pct != null && (
                  <span>
                    PnL:{" "}
                    <span className={p.pnl_pct >= 0 ? "text-emerald-300" : "text-red-300"}>
                      {p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct}%
                    </span>
                  </span>
                )}
                {p.reserves_sol != null && <span>pool: {p.reserves_sol} SOL</span>}
                {p.hold_seconds != null && <span>held: {p.hold_seconds}s</span>}
                {p.reason && <span className="text-amber-300">{p.reason}</span>}
                {p.solscan_url && (
                  <a href={p.solscan_url} target="_blank" rel="noreferrer" className="text-emerald-300 hover:underline">
                    buy tx
                  </a>
                )}
                {p.solscan_sell && (
                  <a href={p.solscan_sell} target="_blank" rel="noreferrer" className="text-blue-300 hover:underline">
                    sell tx
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="text-[10px] text-slate-500 mt-4">
        Fade-the-dump strategy: we settle {cfg.settle_delay_sec ?? "—"}s after detection to skip
        first-slot MEV bots. Real TP/SL via Jupiter reverse quotes.
        Emergency Stop disables live_trader + pump.fun autobuy + graduation executor in-process.
      </div>
    </Card>
  );
}
