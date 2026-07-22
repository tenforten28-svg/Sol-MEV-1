import { useEffect, useState } from "react";
import axios from "axios";
import { Card } from "./ui/card";
import { Badge } from "./ui/badge";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

// Small helper for tiny stat tiles
const Stat = ({ label, value, sub, testId }) => (
  <div data-testid={testId} className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
    <div className="text-[10px] uppercase tracking-widest text-slate-400">{label}</div>
    <div className="text-lg font-semibold text-white mt-1">{value}</div>
    {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
  </div>
);

const shortSig = (s) => (s ? `${s.slice(0, 6)}…${s.slice(-6)}` : "—");

export default function LiveTradingPanel() {
  const [summary, setSummary] = useState(null);
  const [trades, setTrades] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const refresh = async () => {
    try {
      const [s, t, st] = await Promise.all([
        axios.get(`${BACKEND_URL}/api/live/summary`),
        axios.get(`${BACKEND_URL}/api/live/trades?limit=15`),
        axios.get(`${BACKEND_URL}/api/live/status`),
      ]);
      setSummary(s.data);
      setTrades(t.data?.trades || []);
      setStatus(st.data);
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

  const ready = summary?.ready;
  const jitoOn = summary?.jito_enabled;
  const blocked = summary?.risk?.blocked_reason;

  return (
    <Card
      data-testid="live-trading-panel"
      className="bg-gradient-to-br from-rose-950/40 via-slate-900 to-slate-900 border-rose-500/40 p-6 mb-6"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-3 w-3">
              {ready && !blocked && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-500 opacity-75"></span>
              )}
              <span
                className={`relative inline-flex rounded-full h-3 w-3 ${
                  ready && !blocked ? "bg-rose-500" : "bg-slate-500"
                }`}
              ></span>
            </span>
            <h2 className="text-xl font-bold text-white">
              LIVE Trading{" "}
              <span className="text-xs text-rose-300 font-mono ml-2">
                real money · mainnet
              </span>
            </h2>
          </div>
          {summary?.wallet && (
            <p className="text-xs text-slate-400 mt-1 font-mono">
              wallet: {shortSig(summary.wallet)}{" "}
              <a
                href={`https://solscan.io/account/${summary.wallet}`}
                target="_blank"
                rel="noreferrer"
                className="text-rose-400 hover:underline"
                data-testid="wallet-solscan-link"
              >
                (view on Solscan ↗)
              </a>
            </p>
          )}
        </div>

        <div className="flex gap-2 flex-wrap">
          <Badge
            data-testid="live-ready-badge"
            className={
              ready
                ? "bg-rose-500/20 text-rose-300 border-rose-500/50"
                : "bg-slate-700/50 text-slate-400 border-slate-600"
            }
          >
            {ready ? "READY" : "BLOCKED (safe)"}
          </Badge>
          <Badge
            data-testid="jito-status-badge"
            className={
              jitoOn
                ? "bg-purple-500/20 text-purple-300 border-purple-500/50"
                : "bg-slate-700/50 text-slate-400 border-slate-600"
            }
          >
            Jito {jitoOn ? "ON" : "OFF"}
          </Badge>
        </div>
      </div>

      {/* Reason line if not ready */}
      {!ready && status && (
        <div
          data-testid="live-not-ready-reason"
          className="mb-4 rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2 text-xs text-slate-300"
        >
          <span className="text-slate-400">Blocked because: </span>
          {!status.live_enabled && (
            <span className="font-mono text-amber-300">LIVE_TRADING_ENABLED=false </span>
          )}
          {status.simulation_mode && (
            <span className="font-mono text-amber-300">SIMULATION_MODE=true </span>
          )}
          {!status.has_rpc_url && (
            <span className="font-mono text-amber-300">missing SOLANA_RPC_URL </span>
          )}
          {!status.has_private_key && (
            <span className="font-mono text-amber-300">missing SOLANA_PRIVATE_KEY </span>
          )}
          <span className="text-slate-500">— set these on Railway to enable</span>
        </div>
      )}

      {blocked && (
        <div
          data-testid="live-circuit-breaker-reason"
          className="mb-4 rounded-md border border-red-500/40 bg-red-950/30 px-3 py-2 text-xs text-red-300"
        >
          🚨 CIRCUIT BREAKER: {blocked}
        </div>
      )}

      {err && (
        <div className="mb-4 text-xs text-red-400">Fetch error: {err}</div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Stat
          testId="live-wallet-balance"
          label="Wallet SOL"
          value={summary ? summary.sol_balance?.toFixed(4) : "…"}
          sub={
            summary
              ? `≈ $${(summary.sol_balance_usd_estimate ?? 0).toFixed(2)}`
              : ""
          }
        />
        <Stat
          testId="live-trades-today"
          label="Trades Today"
          value={summary?.today?.total_trades ?? "…"}
          sub={
            summary
              ? `${summary.today.successful_trades} success · ${summary.today.success_rate_pct}%`
              : ""
          }
        />
        <Stat
          testId="live-volume-today"
          label="Volume Today"
          value={
            summary ? `$${(summary.today?.total_volume_usd ?? 0).toFixed(2)}` : "…"
          }
          sub={
            summary?.limits
              ? `max ${summary.limits.max_trade_usd}$/trade`
              : ""
          }
        />
        <Stat
          testId="live-day-pnl"
          label="Day P&L"
          value={
            summary
              ? `$${(summary.risk?.day_pnl_usd ?? 0).toFixed(4)}`
              : "…"
          }
          sub={
            summary?.limits
              ? `halt if ≤ -$${summary.limits.daily_loss_limit_usd}`
              : ""
          }
        />
      </div>

      {/* Recent live trades */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-300">
            Recent Live Trades
          </h3>
          <span className="text-[10px] text-slate-500">
            polls every 8s · MongoDB `trades` where simulation=false
          </span>
        </div>

        {loading ? (
          <div className="text-slate-500 text-sm">Loading…</div>
        ) : trades.length === 0 ? (
          <div
            data-testid="live-trades-empty"
            className="text-slate-500 text-sm bg-slate-900/40 border border-slate-800 rounded-md px-3 py-6 text-center"
          >
            No live trades yet. Fire your first one via{" "}
            <code className="text-rose-300">POST /api/live/test_swap</code>{" "}
            (see GO_LIVE_GUIDE.md).
          </div>
        ) : (
          <div
            data-testid="live-trades-list"
            className="max-h-72 overflow-y-auto space-y-2"
          >
            {trades.map((t, i) => (
              <div
                key={t.signature || i}
                data-testid={`live-trade-${i}`}
                className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${
                      t.success ? "bg-emerald-400" : "bg-red-500"
                    }`}
                  />
                  <span className="font-semibold text-white">{t.pair}</span>
                  <span className="text-slate-400 truncate">
                    ${(t.amount_usd || 0).toFixed(2)}
                  </span>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {t.submission_method === "jito_bundle" && (
                    <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/50 text-[10px]">
                      Jito
                    </Badge>
                  )}
                  {t.submission_method === "direct_rpc_fallback" && (
                    <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/50 text-[10px]">
                      fallback
                    </Badge>
                  )}
                  {t.error ? (
                    <span
                      title={t.error}
                      className="text-red-400 text-[10px] truncate max-w-[120px]"
                    >
                      {t.error.slice(0, 30)}
                    </span>
                  ) : t.signature ? (
                    <a
                      href={`https://solscan.io/tx/${t.signature}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-rose-400 hover:underline font-mono"
                      data-testid={`solscan-link-${i}`}
                    >
                      {shortSig(t.signature)} ↗
                    </a>
                  ) : (
                    <span className="text-slate-500">no sig</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
