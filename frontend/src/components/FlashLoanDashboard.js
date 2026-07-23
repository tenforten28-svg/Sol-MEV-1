import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import {
  Activity,
  TrendingUp,
  Target,
  DollarSign,
  Zap,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  BarChart3,
  Settings,
  Calendar
} from 'lucide-react';

const FlashLoanDashboard = () => {
  const [stats, setStats] = useState({
    total_opportunities: 0,
    high_quality_opportunities: 0,
    executed_trades: 0,
    target_trades: 15,
    success_rate: 0,
    total_profit: 0,
    avg_profit_per_trade: 0,
    gas_costs: 0,
    net_profit: 0,
    simulation_failures: 0,
    best_trade: null,
    worst_trade: null,
    uptime_hours: 0,
  });

  const [recentTrades, setRecentTrades] = useState([]);
  const [liveOpportunities, setLiveOpportunities] = useState([]);
  const [dailyStats, setDailyStats] = useState({
    trades_today: 0,
    profit_today: 0,
    unlimited: true,
  });
  const [dailyHistory, setDailyHistory] = useState([]);

  const backendUrl = process.env.REACT_APP_BACKEND_URL;

  useEffect(() => {
    fetchStats();
    fetchRecentTrades();
    fetchLiveOpportunities();
    fetchDailySummary();
    fetchDailyHistory();
    
    const interval = setInterval(() => {
      fetchStats();
      fetchRecentTrades();
      fetchLiveOpportunities();
      fetchDailySummary();
    }, 3000);
    
    // Fetch daily history less frequently (every 30 seconds)
    const historyInterval = setInterval(() => {
      fetchDailyHistory();
    }, 30000);

    return () => {
      clearInterval(interval);
      clearInterval(historyInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchStats = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/flash/stats`);
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (error) {
      console.error('Error fetching flash loan stats:', error);
    }
  };

  const fetchDailySummary = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/flash/daily/summary`);
      if (response.ok) {
        const data = await response.json();
        setDailyStats({
          trades_today: data.trades_executed,
          profit_today: data.profit_today,
          unlimited: data.unlimited || true,
        });
      }
    } catch (error) {
      console.error('Error fetching daily summary:', error);
    }
  };

  const fetchDailyHistory = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/flash/daily/history?days=7`);
      if (response.ok) {
        const data = await response.json();
        setDailyHistory(data);
      }
    } catch (error) {
      console.error('Error fetching daily history:', error);
    }
  };

  const fetchRecentTrades = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/flash/trades?limit=10`);
      if (response.ok) {
        const data = await response.json();
        setRecentTrades(data);
      }
    } catch (error) {
      console.error('Error fetching trades:', error);
    }
  };

  const fetchLiveOpportunities = async () => {
    try {
      const response = await fetch(`${backendUrl}/api/flash/opportunities?limit=5`);
      if (response.ok) {
        const data = await response.json();
        setLiveOpportunities(data);
      }
    } catch (error) {
      console.error('Error fetching opportunities:', error);
    }
  };

  const getStatusColor = (rate) => {
    if (rate >= 80) return 'text-green-500';
    if (rate >= 60) return 'text-yellow-500';
    return 'text-red-500';
  };

  const getQualityBadge = (profit_bps) => {
    if (profit_bps >= 30) return <Badge className="bg-green-500">High Quality</Badge>;
    if (profit_bps >= 20) return <Badge className="bg-blue-500">Good</Badge>;
    if (profit_bps >= 15) return <Badge className="bg-yellow-500">Acceptable</Badge>;
    return <Badge className="bg-gray-500">Low Quality</Badge>;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-4xl font-bold text-white flex items-center gap-3">
              <Zap className="text-yellow-400" />
              Flash Loan Arbitrage Bot
            </h1>
            <p className="text-gray-400 mt-2">
              High-Quality Trade Monitoring • Unlimited Trading
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" className="text-white border-white/20">
              <Settings className="mr-2 h-4 w-4" />
              Settings
            </Button>
          </div>
        </div>

        {/* Today's Summary Card */}
        <Card className="bg-gradient-to-br from-purple-600 to-blue-600 border-0 text-white">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <Calendar className="h-6 w-6" />
              Today's Performance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-5xl font-bold">{dailyStats.trades_today}</p>
                <p className="text-sm opacity-90 mt-1">Trades Executed</p>
                <p className="text-xs opacity-75 mt-1">🚀 Unlimited Trading</p>
              </div>
              <div className="text-right">
                <p className="text-5xl font-bold">${dailyStats.profit_today.toFixed(2)}</p>
                <p className="text-sm opacity-90 mt-1">Total Profit</p>
                <p className="text-xs opacity-75 mt-1">
                  Avg: ${dailyStats.trades_today > 0 ? (dailyStats.profit_today / dailyStats.trades_today).toFixed(2) : '0.00'}/trade
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Daily History Section */}
        <Card className="bg-slate-800/50 border-slate-700">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-white">
              <BarChart3 className="h-5 w-5" />
              Daily Performance History (Last 7 Days)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700">
                    <th className="text-left py-3 px-4 text-gray-400 font-medium">Date</th>
                    <th className="text-right py-3 px-4 text-gray-400 font-medium">Total Trades</th>
                    <th className="text-right py-3 px-4 text-gray-400 font-medium">Successful</th>
                    <th className="text-right py-3 px-4 text-gray-400 font-medium">Success Rate</th>
                    <th className="text-right py-3 px-4 text-gray-400 font-medium">Avg Profit</th>
                    <th className="text-right py-3 px-4 text-gray-400 font-medium">Total Profit</th>
                  </tr>
                </thead>
                <tbody>
                  {dailyHistory.map((day, idx) => (
                    <tr key={idx} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                      <td className="py-3 px-4 text-white font-medium">
                        {new Date(day.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                      </td>
                      <td className="py-3 px-4 text-right text-white">{day.total_trades}</td>
                      <td className="py-3 px-4 text-right text-green-400">{day.successful_trades}</td>
                      <td className="py-3 px-4 text-right">
                        <span className={`${day.success_rate >= 95 ? 'text-green-400' : day.success_rate >= 80 ? 'text-yellow-400' : 'text-red-400'} font-medium`}>
                          {day.success_rate.toFixed(1)}%
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right text-blue-400">${day.avg_profit.toFixed(2)}</td>
                      <td className="py-3 px-4 text-right text-green-400 font-bold">${day.total_profit.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Key Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          
          {/* Total Profit */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Total Net Profit
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-2xl font-bold text-green-400">
                    ${stats.net_profit.toFixed(2)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    Gross: ${stats.total_profit.toFixed(2)}
                  </p>
                </div>
                <DollarSign className="h-8 w-8 text-green-400 opacity-50" />
              </div>
            </CardContent>
          </Card>

          {/* Success Rate */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Success Rate
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-2xl font-bold ${getStatusColor(stats.success_rate)}`}>
                    {stats.success_rate.toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {stats.executed_trades} / {stats.executed_trades + stats.simulation_failures}
                  </p>
                </div>
                <CheckCircle className={`h-8 w-8 ${getStatusColor(stats.success_rate)} opacity-50`} />
              </div>
            </CardContent>
          </Card>

          {/* Avg Profit Per Trade */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Avg Profit / Trade
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-2xl font-bold text-blue-400">
                    ${stats.avg_profit_per_trade.toFixed(2)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    After all fees
                  </p>
                </div>
                <TrendingUp className="h-8 w-8 text-blue-400 opacity-50" />
              </div>
            </CardContent>
          </Card>

          {/* Gas Costs */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Total Gas Costs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-2xl font-bold text-orange-400">
                    ${stats.gas_costs.toFixed(4)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {((stats.gas_costs / stats.total_profit) * 100).toFixed(2)}% of profit
                  </p>
                </div>
                <Activity className="h-8 w-8 text-orange-400 opacity-50" />
              </div>
            </CardContent>
          </Card>

          {/* Flash Loan Fees */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">
                Flash Loan Fees
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-2xl font-bold text-red-400">
                    ${((stats.total_profit - stats.gas_costs) - stats.net_profit).toFixed(2)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    0.09% per loan (~$22.50)
                  </p>
                </div>
                <DollarSign className="h-8 w-8 text-red-400 opacity-50" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Live Opportunities & Recent Trades */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
          {/* Live High-Quality Opportunities */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-white">
                <Zap className="text-yellow-400" />
                Live High-Quality Opportunities
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {liveOpportunities.length > 0 ? (
                  liveOpportunities.map((opp, idx) => (
                    <div 
                      key={idx}
                      className="p-3 bg-slate-700/50 rounded-lg border border-slate-600 hover:border-yellow-500/50 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white">{opp.token_pair}</span>
                          {getQualityBadge(opp.profit_after_flash_loan_bps)}
                        </div>
                        <span className="text-sm text-gray-400">
                          {new Date(opp.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <p className="text-gray-400">Loan Size</p>
                          <p className="text-white font-medium">${opp.loan_size_usd.toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-gray-400">Net Profit</p>
                          <p className="text-green-400 font-bold">${opp.net_profit.toFixed(2)}</p>
                        </div>
                      </div>
                      
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <span className="text-gray-400">
                          {opp.buy_dex} → {opp.sell_dex}
                        </span>
                        <span className="text-blue-400">
                          {opp.profit_after_flash_loan_bps.toFixed(1)} bps
                        </span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    <Activity className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>Scanning for opportunities...</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Recent Trades */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-white">
                <BarChart3 />
                Recent Executed Trades
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {recentTrades.length > 0 ? (
                  recentTrades.slice(0, 8).map((trade, idx) => (
                    <div 
                      key={idx}
                      className="flex items-center justify-between p-2 bg-slate-700/30 rounded hover:bg-slate-700/50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        {trade.success ? (
                          <CheckCircle className="h-4 w-4 text-green-500" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-500" />
                        )}
                        <div>
                          <p className="text-sm font-medium text-white">{trade.token_pair}</p>
                          <p className="text-xs text-gray-500">
                            ${trade.loan_amount.toLocaleString()} • {new Date(trade.timestamp).toLocaleTimeString()}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className={`text-sm font-bold ${trade.net_profit > 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${trade.net_profit.toFixed(2)}
                        </p>
                        <p className="text-xs text-gray-500">
                          {trade.profit_bps.toFixed(1)} bps
                        </p>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    <Clock className="h-12 w-12 mx-auto mb-2 opacity-50" />
                    <p>No trades executed yet</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Performance Metrics */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Best/Worst Trades */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader>
              <CardTitle className="text-white">Trade Performance</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-sm text-gray-400 mb-1">Best Trade</p>
                {stats.best_trade ? (
                  <div className="p-2 bg-green-500/20 border border-green-500/30 rounded">
                    <p className="text-sm text-white">{stats.best_trade.pair}</p>
                    <p className="text-lg font-bold text-green-400">
                      +${stats.best_trade.profit.toFixed(2)}
                    </p>
                  </div>
                ) : (
                  <p className="text-gray-500">No trades yet</p>
                )}
              </div>
              
              <div>
                <p className="text-sm text-gray-400 mb-1">Worst Trade</p>
                {stats.worst_trade ? (
                  <div className="p-2 bg-red-500/20 border border-red-500/30 rounded">
                    <p className="text-sm text-white">{stats.worst_trade.pair}</p>
                    <p className="text-lg font-bold text-red-400">
                      ${stats.worst_trade.profit.toFixed(2)}
                    </p>
                  </div>
                ) : (
                  <p className="text-gray-500">No trades yet</p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* System Health */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader>
              <CardTitle className="text-white">System Health</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Uptime</span>
                <span className="text-white font-medium">{stats.uptime_hours.toFixed(1)}h</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Simulation Failures</span>
                <span className="text-white font-medium">{stats.simulation_failures}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">Opportunities Found</span>
                <span className="text-white font-medium">{stats.total_opportunities}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">High Quality</span>
                <span className="text-green-400 font-medium">{stats.high_quality_opportunities}</span>
              </div>
            </CardContent>
          </Card>

          {/* Critical Alerts */}
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-white">
                <AlertTriangle className="text-yellow-500" />
                Critical Alerts
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {stats.success_rate < 70 && (
                <div className="p-2 bg-yellow-500/20 border border-yellow-500/30 rounded">
                  <p className="text-sm text-yellow-400">⚠️ Low success rate</p>
                </div>
              )}
              
              {dailyStats.trades_today < 5 && (
                <div className="p-2 bg-blue-500/20 border border-blue-500/30 rounded">
                  <p className="text-sm text-blue-400">ℹ️ Below target pace</p>
                </div>
              )}
              
              {stats.simulation_failures > 10 && (
                <div className="p-2 bg-red-500/20 border border-red-500/30 rounded">
                  <p className="text-sm text-red-400">🚨 High simulation failures</p>
                </div>
              )}
              
              {stats.success_rate >= 70 && dailyStats.trades_today >= 5 && stats.simulation_failures <= 10 && (
                <div className="p-2 bg-green-500/20 border border-green-500/30 rounded text-center">
                  <p className="text-sm text-green-400">✅ All systems normal</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

      </div>
    </div>
  );
};

export default FlashLoanDashboard;
