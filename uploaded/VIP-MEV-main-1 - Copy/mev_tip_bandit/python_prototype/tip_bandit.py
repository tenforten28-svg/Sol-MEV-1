#!/usr/bin/env python3
"""
Adaptive Tip Bandit - Python Prototype

Implements Multi-Armed Bandit (UCB1 and Thompson Sampling) for optimizing
validator tips in Solana MEV bot operations.
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from enum import Enum
import json


class AlgorithmType(Enum):
    UCB1 = "ucb1"
    THOMPSON = "thompson"


@dataclass
class TipArm:
    """Represents a single tip level (arm) in the bandit"""
    lamports: int
    pulls: int = 0
    total_reward: float = 0.0
    successes: int = 0
    failures: int = 0
    avg_reward: float = 0.0
    confidence_bound: float = float('inf')
    
    def update(self, reward: float, success: bool):
        """Update arm statistics"""
        self.pulls += 1
        self.total_reward += reward
        self.avg_reward = self.total_reward / self.pulls
        
        if success:
            self.successes += 1
        else:
            self.failures += 1
    
    def win_rate(self) -> float:
        """Calculate inclusion rate"""
        return self.successes / self.pulls if self.pulls > 0 else 0.0


@dataclass
class Opportunity:
    """Represents an arbitrage opportunity"""
    token_pair: str
    expected_profit: float  # In lamports
    size: float
    urgency: float  # 0.0 - 1.0
    timestamp: int


@dataclass
class BundleResult:
    """Result of a bundle submission"""
    included: bool
    tip_used: int
    actual_profit: float
    latency_ms: int
    block_slot: int
    validator_id: str = "sim_validator"
    
    def calculate_reward(self, expected_profit: float) -> float:
        """Calculate normalized reward"""
        if self.included:
            tx_fees = 5000.0
            net_profit = self.actual_profit - tx_fees - self.tip_used
            return max(net_profit / expected_profit, 0.0)
        else:
            return -(self.tip_used / expected_profit)


@dataclass
class MarketCondition:
    """Simulated market conditions"""
    base_inclusion_prob: float
    competing_bots: int
    validator_latency_ms: int
    min_competitive_tip: int


class MarketSimulator:
    """Simulates market conditions and bundle submissions"""
    
    def __init__(self):
        self.current_slot = 1_000_000
        self.market = self._random_market()
    
    def _random_market(self) -> MarketCondition:
        """Generate random market conditions"""
        return MarketCondition(
            base_inclusion_prob=np.random.uniform(0.3, 0.9),
            competing_bots=np.random.randint(5, 50),
            validator_latency_ms=np.random.randint(10, 200),
            min_competitive_tip=np.random.randint(10_000, 80_000)
        )
    
    def simulate_submission(self, tip: int, opportunity: Opportunity) -> BundleResult:
        """Simulate a bundle submission"""
        # Calculate inclusion probability
        if tip < self.market.min_competitive_tip:
            inclusion_prob = 0.1
        else:
            tip_factor = np.log(1 + tip) / np.log(1 + 100_000)
            inclusion_prob = min(self.market.base_inclusion_prob * tip_factor, 0.99)
        
        # Random outcome
        included = np.random.random() < inclusion_prob
        
        # Simulate profit with variance
        actual_profit = opportunity.expected_profit * np.random.uniform(0.8, 1.2) if included else 0.0
        
        self.current_slot += 1
        
        return BundleResult(
            included=included,
            tip_used=tip,
            actual_profit=actual_profit,
            latency_ms=self.market.validator_latency_ms,
            block_slot=self.current_slot
        )
    
    def generate_opportunity(self) -> Opportunity:
        """Generate random opportunity"""
        token_pairs = ["SOL/USDC", "RAY/USDC", "ORCA/USDC"]
        return Opportunity(
            token_pair=np.random.choice(token_pairs),
            expected_profit=np.random.uniform(20_000, 150_000),
            size=np.random.uniform(0.1, 10.0),
            urgency=np.random.random(),
            timestamp=self.current_slot
        )
    
    def update_market(self):
        """Change market conditions"""
        self.market = self._random_market()


class TipBandit:
    """Multi-Armed Bandit for tip optimization"""
    
    def __init__(self, tip_levels: List[int], algorithm: AlgorithmType = AlgorithmType.UCB1,
                 exploration_param: float = 2.0):
        self.arms = [TipArm(lamports=tip) for tip in tip_levels]
        self.total_pulls = 0
        self.algorithm = algorithm
        self.exploration_param = exploration_param
        self.alpha = 1.0  # Thompson prior
        self.beta = 1.0   # Thompson prior
        
        # Tracking
        self.history: List[Tuple[int, BundleResult]] = []
    
    def select_tip_ucb1(self, opportunity: Opportunity) -> int:
        """Select tip using UCB1 algorithm"""
        # Exploration: try each arm at least once
        for arm in self.arms:
            if arm.pulls == 0:
                return arm.lamports
        
        # Exploitation with exploration bonus
        best_arm = None
        best_ucb = -float('inf')
        
        for arm in self.arms:
            exploitation = arm.avg_reward
            exploration = self.exploration_param * np.sqrt(
                (2 * np.log(self.total_pulls)) / arm.pulls
            )
            ucb = exploitation + exploration
            
            # Urgency boost
            if opportunity.urgency > 0.8:
                ucb *= 1.2
            
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = arm
        
        return best_arm.lamports
    
    def select_tip_thompson(self) -> int:
        """Select tip using Thompson Sampling"""
        best_arm = None
        best_sample = -float('inf')
        
        for arm in self.arms:
            # Sample from Beta distribution
            alpha_post = self.alpha + arm.successes
            beta_post = self.beta + arm.failures
            sample = np.random.beta(alpha_post, beta_post)
            
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        
        return best_arm.lamports
    
    def select_tip(self, opportunity: Opportunity) -> int:
        """Select tip based on algorithm"""
        if self.algorithm == AlgorithmType.UCB1:
            return self.select_tip_ucb1(opportunity)
        else:
            return self.select_tip_thompson()
    
    def update(self, result: BundleResult, opportunity: Opportunity):
        """Update bandit state after observing result"""
        reward = result.calculate_reward(opportunity.expected_profit)
        
        # Find and update arm
        for arm in self.arms:
            if arm.lamports == result.tip_used:
                arm.update(reward, result.included)
                break
        
        self.total_pulls += 1
        self.history.append((result.tip_used, result))
        
        # Update confidence bounds for UCB1
        if self.algorithm == AlgorithmType.UCB1:
            self._update_confidence_bounds()
    
    def _update_confidence_bounds(self):
        """Recompute UCB bounds for all arms"""
        for arm in self.arms:
            if arm.pulls > 0:
                exploration = self.exploration_param * np.sqrt(
                    (2 * np.log(self.total_pulls)) / arm.pulls
                )
                arm.confidence_bound = arm.avg_reward + exploration
    
    def get_metrics(self) -> Dict:
        """Calculate performance metrics"""
        win_rates = {arm.lamports: arm.win_rate() for arm in self.arms}
        avg_rewards = {arm.lamports: arm.avg_reward for arm in self.arms}
        
        total_successes = sum(arm.successes for arm in self.arms)
        total_opportunities = sum(arm.pulls for arm in self.arms)
        overall_win_rate = total_successes / total_opportunities if total_opportunities > 0 else 0.0
        
        # Calculate profit
        total_profit = sum(
            result.actual_profit if result.included else 0.0
            for _, result in self.history
        )
        total_cost = sum(result.tip_used for _, result in self.history)
        
        # Convergence
        best_arm = max(self.arms, key=lambda a: a.avg_reward)
        convergence = best_arm.pulls / self.total_pulls if self.total_pulls > 0 else 0.0
        
        return {
            'win_rates': win_rates,
            'avg_rewards': avg_rewards,
            'total_profit': total_profit,
            'total_cost': total_cost,
            'net_profit': total_profit - total_cost,
            'overall_win_rate': overall_win_rate,
            'convergence': convergence,
            'total_pulls': self.total_pulls,
            'best_tip': best_arm.lamports
        }
    
    def print_summary(self):
        """Print performance summary"""
        metrics = self.get_metrics()
        
        print("\n" + "="*50)
        print("ADAPTIVE TIP BANDIT - PERFORMANCE SUMMARY")
        print("="*50)
        print(f"Algorithm: {self.algorithm.value.upper()}")
        print(f"Total Pulls: {metrics['total_pulls']}")
        print(f"Overall Win Rate: {metrics['overall_win_rate']*100:.2f}%")
        print(f"Total Profit: ${metrics['total_profit']/1_000_000:.2f}")
        print(f"Total Cost (Tips): ${metrics['total_cost']/1_000_000:.2f}")
        print(f"Net Profit: ${metrics['net_profit']/1_000_000:.2f}")
        print(f"Convergence: {metrics['convergence']*100:.2f}%")
        print(f"\nRecommended Tip: {metrics['best_tip']:,} lamports")
        
        print("\n" + "-"*50)
        print("Per-Tip Analysis:")
        print("-"*50)
        print(f"{'Tip (lamports)':<15} {'Win Rate':<12} {'Avg Reward':<12} {'Pulls':<8}")
        print("-"*50)
        
        for arm in sorted(self.arms, key=lambda a: a.lamports):
            print(f"{arm.lamports:<15,} {arm.win_rate()*100:>10.2f}% "
                  f"{arm.avg_reward:>11.4f} {arm.pulls:>7}")
        
        print("="*50 + "\n")


def run_simulation(num_rounds: int = 1000, algorithm: AlgorithmType = AlgorithmType.UCB1,
                   plot_results: bool = True) -> TipBandit:
    """Run complete simulation"""
    print(f"\nRunning simulation with {algorithm.value.upper()} algorithm...")
    print(f"Number of rounds: {num_rounds}\n")
    
    # Initialize
    tip_levels = [5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000]
    bandit = TipBandit(tip_levels, algorithm=algorithm)
    simulator = MarketSimulator()
    
    # Run simulation
    regrets = []
    cumulative_rewards = []
    win_rates = []
    total_reward = 0.0
    
    for i in range(num_rounds):
        # Generate opportunity
        opp = simulator.generate_opportunity()
        
        # Select tip
        tip = bandit.select_tip(opp)
        
        # Simulate submission
        result = simulator.simulate_submission(tip, opp)
        
        # Update bandit
        bandit.update(result, opp)
        
        # Track metrics
        reward = result.calculate_reward(opp.expected_profit)
        total_reward += reward
        cumulative_rewards.append(total_reward)
        
        # Calculate instantaneous regret (simplified)
        best_possible = max(arm.avg_reward for arm in bandit.arms if arm.pulls > 0)
        regret = best_possible - reward
        regrets.append(regret)
        
        # Track win rate
        metrics = bandit.get_metrics()
        win_rates.append(metrics['overall_win_rate'])
        
        # Update market occasionally
        if i % 100 == 0 and i > 0:
            simulator.update_market()
            print(f"Round {i}: Win Rate = {metrics['overall_win_rate']*100:.2f}%, "
                  f"Net Profit = ${metrics['net_profit']/1_000_000:.2f}")
    
    # Print final summary
    bandit.print_summary()
    
    # Plot results
    if plot_results:
        plot_simulation_results(bandit, cumulative_rewards, win_rates, regrets)
    
    return bandit


def plot_simulation_results(bandit: TipBandit, cumulative_rewards: List[float],
                           win_rates: List[float], regrets: List[float]):
    """Plot simulation results"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'Adaptive Tip Bandit Simulation - {bandit.algorithm.value.upper()}', fontsize=16)
    
    # 1. Cumulative Reward
    axes[0, 0].plot(cumulative_rewards, linewidth=2, color='green')
    axes[0, 0].set_title('Cumulative Reward Over Time')
    axes[0, 0].set_xlabel('Round')
    axes[0, 0].set_ylabel('Cumulative Reward')
    axes[0, 0].grid(True, alpha=0.3)
    
    # 2. Win Rate
    axes[0, 1].plot(win_rates, linewidth=2, color='blue')
    axes[0, 1].set_title('Win Rate (Inclusion Rate) Over Time')
    axes[0, 1].set_xlabel('Round')
    axes[0, 1].set_ylabel('Win Rate')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].set_ylim([0, 1])
    
    # 3. Arm Pull Distribution
    tips = [arm.lamports for arm in bandit.arms]
    pulls = [arm.pulls for arm in bandit.arms]
    axes[1, 0].bar(range(len(tips)), pulls, color='purple', alpha=0.7)
    axes[1, 0].set_title('Arm Selection Distribution')
    axes[1, 0].set_xlabel('Tip Level')
    axes[1, 0].set_ylabel('Number of Pulls')
    axes[1, 0].set_xticks(range(len(tips)))
    axes[1, 0].set_xticklabels([f'{t//1000}k' for t in tips], rotation=45)
    axes[1, 0].grid(True, alpha=0.3, axis='y')
    
    # 4. Average Reward per Tip
    avg_rewards = [arm.avg_reward for arm in bandit.arms]
    axes[1, 1].bar(range(len(tips)), avg_rewards, color='orange', alpha=0.7)
    axes[1, 1].set_title('Average Reward per Tip Level')
    axes[1, 1].set_xlabel('Tip Level')
    axes[1, 1].set_ylabel('Average Reward')
    axes[1, 1].set_xticks(range(len(tips)))
    axes[1, 1].set_xticklabels([f'{t//1000}k' for t in tips], rotation=45)
    axes[1, 1].grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig('/app/mev_tip_bandit/python_prototype/simulation_results.png', dpi=150)
    print("\n✅ Plot saved to: simulation_results.png\n")
    # Don't show in headless environment
    # plt.show()


def compare_algorithms(num_rounds: int = 1000):
    """Compare UCB1 vs Thompson Sampling"""
    print("\n" + "="*60)
    print("COMPARING ALGORITHMS: UCB1 vs THOMPSON SAMPLING")
    print("="*60)
    
    # Run both algorithms
    ucb1_bandit = run_simulation(num_rounds, AlgorithmType.UCB1, plot_results=False)
    thompson_bandit = run_simulation(num_rounds, AlgorithmType.THOMPSON, plot_results=False)
    
    # Compare metrics
    ucb1_metrics = ucb1_bandit.get_metrics()
    thompson_metrics = thompson_bandit.get_metrics()
    
    print("\n" + "="*60)
    print("COMPARISON RESULTS")
    print("="*60)
    print(f"{'Metric':<25} {'UCB1':<15} {'Thompson':<15}")
    print("-"*60)
    print(f"{'Win Rate':<25} {ucb1_metrics['overall_win_rate']*100:>13.2f}% "
          f"{thompson_metrics['overall_win_rate']*100:>13.2f}%")
    print(f"{'Net Profit':<25} ${ucb1_metrics['net_profit']/1_000_000:>12.2f} "
          f"${thompson_metrics['net_profit']/1_000_000:>12.2f}")
    print(f"{'Convergence':<25} {ucb1_metrics['convergence']*100:>13.2f}% "
          f"{thompson_metrics['convergence']*100:>13.2f}%")
    print(f"{'Best Tip':<25} {ucb1_metrics['best_tip']:>13,} "
          f"{thompson_metrics['best_tip']:>13,}")
    print("="*60 + "\n")


if __name__ == "__main__":
    # Run single simulation
    bandit = run_simulation(num_rounds=1000, algorithm=AlgorithmType.UCB1)
    
    # Optionally compare algorithms
    # compare_algorithms(num_rounds=1000)
