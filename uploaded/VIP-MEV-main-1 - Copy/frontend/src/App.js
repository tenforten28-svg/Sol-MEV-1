import { useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import Dashboard from "@/components/Dashboard";
import MemeDashboard from "@/components/MemeDashboard";
import FlashLoanDashboard from "@/components/FlashLoanDashboard";
import { Toaster } from '@/components/ui/sonner';
import { Coins, TrendingUp } from 'lucide-react';

function Navigation() {
  const location = useLocation();
  
  const isActive = (path) => location.pathname === path;
  
  return (
    <div className="bg-slate-900 border-b border-slate-700 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-8 h-8 text-emerald-400" />
            <h1 className="text-2xl font-bold text-white">Solana Arbitrage Bot</h1>
          </div>
          <nav className="flex gap-4">
            {/* Deactivated - Stablecoin Bot
            <Link 
              to="/" 
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                isActive('/') 
                  ? 'bg-emerald-500 text-white' 
                  : 'bg-slate-800 text-gray-300 hover:bg-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                <Coins className="w-4 h-4" />
                Stable Coins
              </span>
            </Link>
            */}
            {/* Deactivated - Meme Coin Bot
            <Link 
              to="/memes" 
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                isActive('/memes') 
                  ? 'bg-purple-500 text-white' 
                  : 'bg-slate-800 text-gray-300 hover:bg-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                🎭
                Meme Coins
              </span>
            </Link>
            */}
            <Link 
              to="/flash" 
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                isActive('/flash') 
                  ? 'bg-yellow-500 text-white' 
                  : 'bg-slate-800 text-gray-300 hover:bg-slate-700'
              }`}
            >
              <span className="flex items-center gap-2">
                ⚡
                Flash Loans
              </span>
            </Link>
          </nav>
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Navigation />
        <Routes>
          <Route path="/" element={<FlashLoanDashboard />} />
          <Route path="/flash" element={<FlashLoanDashboard />} />
          {/* Deactivated routes */}
          {/* <Route path="/stablecoin" element={<Dashboard />} /> */}
          {/* <Route path="/memes" element={<MemeDashboard />} /> */}
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </div>
  );
}

export default App;