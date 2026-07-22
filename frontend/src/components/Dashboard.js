import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { TrendingUp, TrendingDown, Activity, DollarSign, Target, Zap, Play, Pause } from 'lucide-react';
import LiveTradingPanel from './LiveTradingPanel';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Dashboard = () => {
  const [opportunities, setOpportunities] = useState([]);
  const [trades, setTrades] = useState([]);
  const [stats, setStats] = useState(null);
  const [config, setConfig] = useState(null);
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);

  // Fetch initial data
  const fetchData = useCallback(async () => {
    try {
      const [oppsRes, tradesRes, statsRes, configRes] = await Promise.all([
        axios.get(`${API}/opportunities`),
        axios.get(`${API}/trades?limit=20`),
        axios.get(`${API}/stats`),
        axios.get(`${API}/config`)
      ]);

      setOpportunities(oppsRes.data);
      setTrades(tradesRes.data);
      setStats(statsRes.data);
      setConfig(configRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
      toast.error('Failed to fetch data');
    }
  }, []);

  // WebSocket connection
  useEffect(() => {
    const wsUrl = `${BACKEND_URL.replace('https', 'wss').replace('http', 'ws')}/api/ws`;
    const websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
      setIsConnected(true);
      console.log('WebSocket connected');
    };

    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'new_opportunity') {
        setOpportunities(prev => [data.opportunity, ...prev].slice(0, 50));
        toast.success('New arbitrage opportunity found!');
      } else if (data.type === 'trade_executed') {
        setTrades(prev => [data.trade, ...prev].slice(0, 20));
        fetchData(); // Refresh stats
      }
    };

    websocket.onerror = () => {
      setIsConnected(false);
    };

    websocket.onclose = () => {
      setIsConnected(false);
      console.log('WebSocket disconnected');
    };

    setWs(websocket);

    return () => {
      websocket.close();
    };
  }, [BACKEND_URL, fetchData]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000); // Refresh every 10s
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleSimulationMode = async () => {
    try {
      const updatedConfig = { ...config, simulation_mode: !config.simulation_mode };
      await axios.post(`${API}/config`, updatedConfig);
      setConfig(updatedConfig);
      toast.success(`Simulation mode ${!config.simulation_mode ? 'enabled' : 'disabled'}`);
    } catch (error) {
      toast.error('Failed to update configuration');
    }
  };

  const executeTrade = async (opportunityId, amount) => {
    try {
      const response = await axios.post(`${API}/execute`, {
        opportunity_id: opportunityId,
        amount: amount
      });
      
      if (response.data.success) {
        toast.success(`Trade executed ${response.data.simulation ? '(Simulated)' : 'successfully'}`);
        fetchData();
      } else {
        toast.error(response.data.error || 'Failed to execute trade');
      }
    } catch (error) {
      toast.error('Failed to execute trade');
    }
  };

  const formatTime = (timestamp) => {
    return new Date(timestamp).toLocaleTimeString();
  };
  
  const getOpportunityAge = (timestamp) => {
    const now = new Date();
    const oppTime = new Date(timestamp);
    const ageSeconds = Math.floor((now - oppTime) / 1000);
    
    if (ageSeconds < 10) return { text: `${ageSeconds}s ago`, color: 'text-emerald-400' };
    if (ageSeconds < 30) return { text: `${ageSeconds}s ago`, color: 'text-yellow-400' };
    if (ageSeconds < 60) return { text: `${ageSeconds}s ago`, color: 'text-orange-400' };
    return { text: `${Math.floor(ageSeconds / 60)}m ago`, color: 'text-red-400' };
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-purple-950/20 to-slate-950 p-4 md:p-8">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-400 bg-clip-text text-transparent mb-2" data-testid="dashboard-title">
              Solana MEV Bot
            </h1>
            <p className="text-gray-400 text-sm md:text-base" data-testid="dashboard-subtitle">
              Multi-DEX Arbitrage Hunter • Serum • Raydium • Orca
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-slate-800/50 backdrop-blur-sm border border-slate-700">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} data-testid="connection-status"></div>
              <span className="text-sm text-gray-300">{isConnected ? 'Live' : 'Disconnected'}</span>
            </div>
            {config && (
              <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-slate-800/50 backdrop-blur-sm border border-slate-700">
                <span className="text-sm text-gray-300">Simulation</span>
                <Switch 
                  checked={config.simulation_mode} 
                  onCheckedChange={toggleSimulationMode}
                  data-testid="simulation-toggle"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* LIVE TRADING PANEL — separate from simulation stats below */}
      <div className="max-w-7xl mx-auto">
        <LiveTradingPanel />
      </div>

      {/* Stats Cards */}
      {stats && (
        <>
        <div className="max-w-7xl mx-auto mb-2 flex items-center gap-2">
          <span className="text-xs uppercase tracking-widest text-slate-500 font-mono">
            ↓ Simulation Bot Stats (paper trading only)
          </span>
          <div className="flex-1 h-px bg-slate-800"></div>
        </div>
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/90 border-slate-700 backdrop-blur-sm" data-testid="stat-card-opportunities">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-400 flex items-center gap-2">
                <Target className="w-4 h-4" />
                Recent Opportunities
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-emerald-400">{stats.total_opportunities}</div>
              <p className="text-xs text-gray-500 mt-1">Found in last 2 min</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/90 border-slate-700 backdrop-blur-sm" data-testid="stat-card-trades">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-400 flex items-center gap-2">
                <Zap className="w-4 h-4" />
                Executed Trades
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-cyan-400">{stats.executed_trades}</div>
              <p className="text-xs text-gray-500 mt-1">Success rate: {stats.success_rate.toFixed(1)}%</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/90 border-slate-700 backdrop-blur-sm" data-testid="stat-card-profit">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-400 flex items-center gap-2">
                <DollarSign className="w-4 h-4" />
                Total Profit
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-emerald-400">${stats.total_profit.toFixed(2)}</div>
              <p className="text-xs text-gray-500 mt-1">Cumulative earnings</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900/90 to-slate-800/90 border-slate-700 backdrop-blur-sm" data-testid="stat-card-pairs">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-400 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Active Pairs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-purple-400">{stats.active_pairs}</div>
              <p className="text-xs text-gray-500 mt-1">Being monitored</p>
            </CardContent>
          </Card>
        </div>
        </>
      )}

      {/* Main Content */}
      <div className="max-w-7xl mx-auto">
        <Tabs defaultValue="opportunities" className="space-y-4">
          <TabsList className="bg-slate-900/90 border border-slate-700 p-1" data-testid="tabs-list">
            <TabsTrigger value="opportunities" className="data-[state=active]:bg-emerald-500/20 data-[state=active]:text-emerald-400" data-testid="tab-opportunities">
              Live Opportunities
            </TabsTrigger>
            <TabsTrigger value="trades" className="data-[state=active]:bg-cyan-500/20 data-[state=active]:text-cyan-400" data-testid="tab-trades">
              Trade History
            </TabsTrigger>
          </TabsList>

          <TabsContent value="opportunities" className="space-y-4">
            <Card className="bg-slate-900/90 border-slate-700 backdrop-blur-sm" data-testid="opportunities-card">
              <CardHeader>
                <CardTitle className="text-xl text-emerald-400">Active Opportunities (Live Feed)</CardTitle>
                <CardDescription>Showing opportunities from the last 2 minutes • Green badges indicate auto-executed trades</CardDescription>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[600px] pr-4">
                  {opportunities.length === 0 ? (
                    <div className="text-center py-12 text-gray-500" data-testid="no-opportunities">
                      <Target className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>No opportunities found yet</p>
                      <p className="text-sm mt-2">Bot is scanning DEXs...</p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {opportunities.map((opp, idx) => (
                        <div 
                          key={opp.id} 
                          className={`p-4 rounded-lg border transition-all ${
                            opp.executed 
                              ? 'bg-gradient-to-r from-emerald-900/20 to-emerald-800/10 border-emerald-700/40 opacity-75' 
                              : 'bg-gradient-to-r from-slate-800/50 to-slate-800/30 border-slate-700 hover:border-emerald-500/50'
                          }`}
                          data-testid={`opportunity-${idx}`}
                        >
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                              <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30">
                                {opp.token_pair}
                              </Badge>
                              {opp.executed && (
                                <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-xs">
                                  ✓ Auto-Executed
                                </Badge>
                              )}
                              <span className={`text-xs font-semibold ${getOpportunityAge(opp.timestamp).color}`}>
                                {getOpportunityAge(opp.timestamp).text}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <TrendingUp className="w-4 h-4 text-emerald-400" />
                              <span className="text-lg font-bold text-emerald-400">
                                +{(opp.net_profit_percentage || opp.profit_percentage || 0).toFixed(2)}%
                              </span>
                            </div>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-4 mb-3">
                            <div className="space-y-1">
                              <p className="text-xs text-gray-500">Buy on {opp.dex_buy.toUpperCase()}</p>
                              <p className="text-sm font-semibold text-gray-300">${opp.buy_price.toFixed(4)}</p>
                            </div>
                            <div className="space-y-1">
                              <p className="text-xs text-gray-500">Sell on {opp.dex_sell.toUpperCase()}</p>
                              <p className="text-sm font-semibold text-gray-300">${opp.sell_price.toFixed(4)}</p>
                            </div>
                          </div>

                          <Separator className="my-3 bg-slate-700" />

                          <div className="flex items-center justify-between">
                            <div className="flex gap-6">
                              <div>
                                <p className="text-xs text-gray-500">Trade Amount</p>
                                <p className="text-sm font-semibold text-gray-300">${(opp.trade_amount || 0).toFixed(4)}</p>
                              </div>
                              <div>
                                <p className="text-xs text-gray-500">Est. Profit</p>
                                <p className="text-sm font-semibold text-emerald-400">${(opp.net_profit_amount || opp.profit_amount || 0).toFixed(4)}</p>
                              </div>
                            </div>
                            {!opp.executed && (
                              <Button 
                                size="sm" 
                                className="bg-emerald-500 hover:bg-emerald-600 text-white"
                                onClick={() => executeTrade(opp.id, opp.trade_amount || config?.max_trade_size || 0.1)}
                                data-testid={`execute-btn-${idx}`}
                              >
                                <Play className="w-4 h-4 mr-1" />
                                Execute
                              </Button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="trades" className="space-y-4">
            <Card className="bg-slate-900/90 border-slate-700 backdrop-blur-sm" data-testid="trades-card">
              <CardHeader>
                <CardTitle className="text-xl text-cyan-400">Trade Execution History</CardTitle>
                <CardDescription>Recent arbitrage trades</CardDescription>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[600px] pr-4">
                  {trades.length === 0 ? (
                    <div className="text-center py-12 text-gray-500" data-testid="no-trades">
                      <Activity className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>No trades executed yet</p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {trades.map((trade, idx) => (
                        <div 
                          key={trade.id} 
                          className="p-4 rounded-lg bg-gradient-to-r from-slate-800/50 to-slate-800/30 border border-slate-700"
                          data-testid={`trade-${idx}`}
                        >
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                              <Badge className="bg-cyan-500/20 text-cyan-300 border-cyan-500/30">
                                {trade.token_pair}
                              </Badge>
                              {trade.simulation && (
                                <Badge className="bg-yellow-500/20 text-yellow-300 border-yellow-500/30">
                                  Simulated
                                </Badge>
                              )}
                              <span className="text-sm text-gray-400">{formatTime(trade.timestamp)}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <TrendingUp className="w-4 h-4 text-emerald-400" />
                              <span className="font-bold text-emerald-400">
                                +${trade.profit.toFixed(4)}
                              </span>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <p className="text-gray-500">Route</p>
                              <p className="text-gray-300">{trade.dex_buy.toUpperCase()} → {trade.dex_sell.toUpperCase()}</p>
                            </div>
                            <div>
                              <p className="text-gray-500">Status</p>
                              <Badge className={`
                                ${trade.status === 'completed' ? 'bg-emerald-500/20 text-emerald-300' : ''}
                                ${trade.status === 'simulated' ? 'bg-yellow-500/20 text-yellow-300' : ''}
                                ${trade.status === 'failed' ? 'bg-red-500/20 text-red-300' : ''}
                              `}>
                                {trade.status}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
};

export default Dashboard;