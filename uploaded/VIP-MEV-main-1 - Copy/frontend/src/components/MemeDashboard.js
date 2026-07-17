import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { TrendingUp, Coins, Activity, DollarSign, Zap, AlertCircle } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

function MemeDashboard() {
  const [stats, setStats] = useState({
    pool_balance: 10.0,
    initial_capital: 10.0,
    total_trades: 0,
    total_profit: 0,
    active_opportunities: 0,
    meme_pairs_monitored: 0,
    tokens_tracked: 0,
    success_rate: 0,
    can_trade: true
  });
  
  const [opportunities, setOpportunities] = useState([]);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  // Fetch meme stats
  const fetchStats = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/meme/stats`);
      const data = await response.json();
      setStats(data);
    } catch (error) {
      console.error('Error fetching meme stats:', error);
    }
  };

  // Fetch opportunities
  const fetchOpportunities = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/meme/opportunities`);
      const data = await response.json();
      setOpportunities(data);
    } catch (error) {
      console.error('Error fetching opportunities:', error);
    }
  };

  // Fetch trades
  const fetchTrades = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/meme/trades`);
      const data = await response.json();
      setTrades(data);
    } catch (error) {
      console.error('Error fetching trades:', error);
    }
  };

  useEffect(() => {
    const fetchAllData = async () => {
      setLoading(true);
      await Promise.all([fetchStats(), fetchOpportunities(), fetchTrades()]);
      setLoading(false);
    };

    fetchAllData();
    
    // Refresh every 3 seconds
    const interval = setInterval(() => {
      fetchStats();
      fetchOpportunities();
      fetchTrades();
    }, 3000);

    return () => clearInterval(interval);
  }, []);

  const formatTime = (timestamp) => {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  const getOpportunityAge = (timestamp) => {
    if (!timestamp) return { text: 'Unknown', color: 'text-gray-500' };
    
    const now = new Date();
    const oppTime = new Date(timestamp);
    const secondsAgo = Math.floor((now - oppTime) / 1000);
    
    if (secondsAgo < 10) {
      return { text: `${secondsAgo}s ago`, color: 'text-emerald-400' };
    } else if (secondsAgo < 60) {
      return { text: `${secondsAgo}s ago`, color: 'text-yellow-400' };
    } else {
      const minutesAgo = Math.floor(secondsAgo / 60);
      return { text: `${minutesAgo}m ago`, color: 'text-orange-400' };
    }
  };

  const availableCapital = stats.pool_balance * (1 - stats.reserve_percentage / 100);
  const profitPercent = stats.initial_capital > 0 
    ? ((stats.total_profit / stats.initial_capital) * 100).toFixed(2)
    : 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
        <div className="text-white text-xl">Loading Meme Dashboard...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-pink-400">
              🎭 Meme Coin Trading
            </h1>
            <p className="text-gray-400 mt-2">Separate strategy for volatile meme coins</p>
          </div>
          <div className="flex items-center gap-2">
            {stats.can_trade ? (
              <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30">
                <Zap className="w-3 h-3 mr-1" />
                Active
              </Badge>
            ) : (
              <Badge className="bg-red-500/20 text-red-300 border-red-500/30">
                <AlertCircle className="w-3 h-3 mr-1" />
                Cooldown
              </Badge>
            )}
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          
          {/* Pool Balance */}
          <Card className="bg-gradient-to-br from-purple-900/90 to-purple-800/90 border-purple-700 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <Coins className="w-4 h-4" />
                Meme Pool Balance
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-purple-300">{stats.pool_balance.toFixed(2)} SOL</div>
              <p className="text-xs text-gray-400 mt-1">
                Available: {availableCapital.toFixed(2)} SOL
              </p>
            </CardContent>
          </Card>

          {/* Total Profit */}
          <Card className="bg-gradient-to-br from-emerald-900/90 to-emerald-800/90 border-emerald-700 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <DollarSign className="w-4 h-4" />
                Total Profit
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-emerald-300">
                ${stats.total_profit.toFixed(2)}
              </div>
              <p className="text-xs text-gray-400 mt-1">
                ROI: {profitPercent}%
              </p>
            </CardContent>
          </Card>

          {/* Executed Trades */}
          <Card className="bg-gradient-to-br from-blue-900/90 to-blue-800/90 border-blue-700 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Meme Trades
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-blue-300">{stats.total_trades}</div>
              <p className="text-xs text-gray-400 mt-1">
                Win Rate: {stats.success_rate.toFixed(1)}%
              </p>
            </CardContent>
          </Card>

          {/* Active Opportunities */}
          <Card className="bg-gradient-to-br from-pink-900/90 to-pink-800/90 border-pink-700 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-300 flex items-center gap-2">
                <TrendingUp className="w-4 h-4" />
                Live Opportunities
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-pink-300">{stats.active_opportunities}</div>
              <p className="text-xs text-gray-400 mt-1">
                {stats.tokens_tracked} tokens, {stats.meme_pairs_monitored} pairs
              </p>
            </CardContent>
          </Card>

        </div>

        {/* Main Content Tabs */}
        <Tabs defaultValue="opportunities" className="w-full">
          <TabsList className="grid w-full grid-cols-2 bg-slate-800/50">
            <TabsTrigger value="opportunities">Live Opportunities</TabsTrigger>
            <TabsTrigger value="history">Trade History</TabsTrigger>
          </TabsList>

          {/* Opportunities Tab */}
          <TabsContent value="opportunities" className="mt-4">
            <Card className="bg-slate-900/90 border-slate-700 backdrop-blur-sm">
              <CardHeader>
                <CardTitle className="text-xl text-purple-400">Meme Coin Opportunities</CardTitle>
                <CardDescription>
                  Conservative: Min 0.15% profit, $100K liquidity, max 0.3% slippage
                </CardDescription>
              </CardHeader>
              <CardContent>
                {opportunities.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>No meme opportunities detected yet</p>
                    <p className="text-sm mt-2">Scanning {stats.meme_pairs_monitored} pairs every 5 seconds...</p>
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[600px] overflow-y-auto">
                    {opportunities.map((opp, idx) => (
                      <div 
                        key={opp.id || idx}
                        className="p-4 rounded-lg bg-gradient-to-r from-purple-900/30 to-pink-900/30 border border-purple-700/50 hover:border-purple-500/70 transition-all"
                      >
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-3">
                            <Badge className="bg-pink-500/20 text-pink-300 border-pink-500/30">
                              {opp.type === 'simple' ? '📊 Simple' : '🔺 Triangular'}
                            </Badge>
                            <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30">
                              {opp.pair || opp.path}
                            </Badge>
                            <span className={`text-xs font-semibold ${getOpportunityAge(opp.discovered_at).color}`}>
                              {getOpportunityAge(opp.discovered_at).text}
                            </span>
                            {opp.safe && (
                              <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-xs">
                                ✓ Safe Liquidity
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <TrendingUp className="w-4 h-4 text-emerald-400" />
                            <span className="text-lg font-bold text-emerald-400">
                              +{opp.net_profit_bps.toFixed(2)} bps
                            </span>
                          </div>
                        </div>

                        {opp.type === 'simple' ? (
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <p className="text-gray-500 text-xs">Buy on {opp.buy_dex?.toUpperCase()}</p>
                              <p className="text-gray-300 font-semibold">${opp.buy_price?.toFixed(6)}</p>
                            </div>
                            <div>
                              <p className="text-gray-500 text-xs">Sell on {opp.sell_dex?.toUpperCase()}</p>
                              <p className="text-gray-300 font-semibold">${opp.sell_price?.toFixed(6)}</p>
                            </div>
                            <div>
                              <p className="text-gray-500 text-xs">Liquidity</p>
                              <p className="text-gray-300 font-semibold">${opp.liquidity_usd?.toLocaleString()}</p>
                            </div>
                            <div>
                              <p className="text-gray-500 text-xs">Slippage</p>
                              <p className="text-gray-300 font-semibold">{opp.slippage_bps?.toFixed(1)} bps</p>
                            </div>
                          </div>
                        ) : (
                          <div className="space-y-2 text-sm">
                            <div className="grid grid-cols-2 gap-4">
                              <div>
                                <p className="text-gray-500 text-xs">Leg 1: {opp.leg1?.pair}</p>
                                <p className="text-gray-300 font-semibold">
                                  {opp.leg1?.dex?.toUpperCase()} @ ${opp.leg1?.price?.toFixed(6)}
                                </p>
                              </div>
                              <div>
                                <p className="text-gray-500 text-xs">Leg 2: {opp.leg2?.pair}</p>
                                <p className="text-gray-300 font-semibold">
                                  {opp.leg2?.dex?.toUpperCase()} @ ${opp.leg2?.price?.toFixed(6)}
                                </p>
                              </div>
                            </div>
                            <div className="text-xs text-purple-300">
                              Path: {opp.path}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Trade History Tab */}
          <TabsContent value="history" className="mt-4">
            <Card className="bg-slate-900/90 border-slate-700 backdrop-blur-sm">
              <CardHeader>
                <CardTitle className="text-xl text-purple-400">Meme Trade History</CardTitle>
                <CardDescription>Recent meme coin arbitrage executions</CardDescription>
              </CardHeader>
              <CardContent>
                {trades.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>No trades executed yet</p>
                    <p className="text-sm mt-2">Waiting for profitable opportunities...</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b border-slate-700">
                          <th className="text-left py-3 px-4 text-gray-400 text-sm">Time</th>
                          <th className="text-left py-3 px-4 text-gray-400 text-sm">Type</th>
                          <th className="text-left py-3 px-4 text-gray-400 text-sm">Pair/Path</th>
                          <th className="text-left py-3 px-4 text-gray-400 text-sm">DEXs</th>
                          <th className="text-right py-3 px-4 text-gray-400 text-sm">Amount</th>
                          <th className="text-right py-3 px-4 text-gray-400 text-sm">Profit</th>
                          <th className="text-right py-3 px-4 text-gray-400 text-sm">ROI</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map((trade, idx) => (
                          <tr key={trade.id || idx} className="border-b border-slate-800 hover:bg-slate-800/50">
                            <td className="py-3 px-4 text-sm text-gray-300">
                              {formatTime(trade.timestamp)}
                            </td>
                            <td className="py-3 px-4">
                              <Badge className={trade.type === 'simple' ? 'bg-blue-500/20 text-blue-300' : 'bg-purple-500/20 text-purple-300'}>
                                {trade.type}
                              </Badge>
                            </td>
                            <td className="py-3 px-4 text-sm text-gray-300 font-semibold">
                              {trade.token_pair}
                            </td>
                            <td className="py-3 px-4 text-xs text-gray-400">
                              {trade.buy_dex} → {trade.sell_dex}
                            </td>
                            <td className="py-3 px-4 text-sm text-gray-300 text-right">
                              {trade.buy_amount?.toFixed(4)} SOL
                            </td>
                            <td className="py-3 px-4 text-sm text-emerald-400 font-semibold text-right">
                              +${trade.profit?.toFixed(4)}
                            </td>
                            <td className="py-3 px-4 text-sm text-emerald-400 text-right">
                              {trade.profit_percentage?.toFixed(2)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

        </Tabs>

        {/* Info Banner */}
        <Card className="bg-purple-900/20 border-purple-700/50">
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-purple-400 mt-0.5" />
              <div className="text-sm text-gray-300">
                <p className="font-semibold text-purple-300 mb-1">Meme Trading Info</p>
                <p className="text-gray-400">
                  This is a separate 10 SOL pool with conservative settings. 
                  Tracking 8 meme coins (BONK, WIF, POPCAT, MEW, MYRO, SAMO, PONKE, SLERF) across 17 pairs.
                  Requires $100K+ liquidity and 30+ day locks for safety.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

      </div>
    </div>
  );
}

export default MemeDashboard;
