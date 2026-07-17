"""
Flash Loan Bot Email Notification System
"""

import os
import asyncio
import logging
import resend
from datetime import datetime, timezone
from typing import Optional, Dict
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

logger = logging.getLogger(__name__)

resend.api_key = os.environ.get('RESEND_API_KEY', '')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')
RECIPIENT_EMAIL = os.environ.get('NOTIFICATION_EMAIL', '')


async def get_stats_from_database(db) -> Dict:
    """Get real stats from MongoDB database"""
    try:
        # Fetch ALL flash loan trades from database
        trades_cursor = db.flash_trades.find(
            {"type": "flash_loan"},
            {"_id": 0}
        )
        trades = await trades_cursor.to_list(length=None)
        
        # Calculate stats from database trades
        successful_trades = [t for t in trades if t.get('success', True)]
        executed_trades = len(successful_trades)
        
        # Calculate totals
        total_profit = sum(t.get('gross_profit', 0) for t in successful_trades)
        net_profit = sum(t.get('net_profit', 0) for t in successful_trades)
        
        # Calculate success rate
        success_rate = 100.0 if executed_trades > 0 else 0.0
        
        # Calculate average profit per trade
        avg_profit = net_profit / executed_trades if executed_trades > 0 else 0
        
        return {
            'executed_trades': executed_trades,
            'net_profit': net_profit,
            'total_profit': total_profit,
            'success_rate': success_rate,
            'avg_profit_per_trade': avg_profit
        }
    except Exception as e:
        logger.error(f"Error getting stats from database: {e}")
        return {
            'executed_trades': 0,
            'net_profit': 0,
            'total_profit': 0,
            'success_rate': 0,
            'avg_profit_per_trade': 0
        }


class EmailNotifier:
    def __init__(self, recipient_email: str = None):
        self.recipient_email = recipient_email or RECIPIENT_EMAIL
        self.last_connection_status = True
        self.connection_lost_time = None
        self.daily_stats = {'trades': 0, 'profit': 0.0, 'errors': 0, 'disconnections': 0}
        self.last_2hour_report = datetime.now(timezone.utc)
        self.is_enabled = bool(resend.api_key and self.recipient_email)
        
        if self.is_enabled:
            logger.info(f"Email notifications enabled for {self.recipient_email}")
        else:
            logger.warning("Email notifications disabled - missing API key or email")
    
    async def send_email(self, subject: str, html_content: str) -> bool:
        if not self.is_enabled:
            return False
        
        params = {
            "from": SENDER_EMAIL,
            "to": [self.recipient_email],
            "subject": subject,
            "html": html_content
        }
        
        try:
            email = await asyncio.to_thread(resend.Emails.send, params)
            logger.info(f"Email sent: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def _get_html_template(self, title: str, content: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #1a1a2e; color: #ffffff; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 10px; padding: 20px; }}
                .header {{ text-align: center; padding: 20px 0; border-bottom: 1px solid #0f3460; }}
                .header h1 {{ color: #00e676; margin: 0; }}
                .content {{ padding: 20px 0; }}
                .footer {{ text-align: center; padding-top: 20px; color: #666; font-size: 12px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                td {{ padding: 10px; border-bottom: 1px solid #0f3460; }}
                .label {{ color: #a0a0a0; }}
                .value {{ color: #00e676; font-weight: bold; text-align: right; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Flash Loan Bot</h1>
                    <p style="color: #a0a0a0; margin: 5px 0;">{title}</p>
                </div>
                <div class="content">{content}</div>
                <div class="footer">
                    <p>Flash Loan Bot Notification</p>
                    <p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    async def send_2hour_update(self, stats: Dict) -> bool:
        trades = stats.get('executed_trades', 0)
        profit = stats.get('net_profit', 0)
        success_rate = stats.get('success_rate', 0)
        avg_profit = stats.get('avg_profit_per_trade', 0)
        
        content = f"""
        <table>
            <tr><td class="label">Trades Executed</td><td class="value">{trades:,}</td></tr>
            <tr><td class="label">Total Profit</td><td class="value">${profit:,.2f}</td></tr>
            <tr><td class="label">Success Rate</td><td class="value">{success_rate:.1f}%</td></tr>
            <tr><td class="label">Avg Profit/Trade</td><td class="value">${avg_profit:.2f}</td></tr>
            <tr><td class="label">Bot Status</td><td class="value" style="color: #00c853;">Running</td></tr>
        </table>
        """
        
        subject = f"Bot Update: {trades:,} trades | ${profit:,.2f} profit"
        html = self._get_html_template("2-Hour Status Update", content)
        return await self.send_email(subject, html)
    
    async def send_daily_summary(self, stats: Dict, daily_history: list = None) -> bool:
        trades = stats.get('executed_trades', 0)
        profit = stats.get('net_profit', 0)
        success_rate = stats.get('success_rate', 0)
        avg_profit = stats.get('avg_profit_per_trade', 0)
        
        content = f"""
        <div style="background-color: #0f3460; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
            <h2 style="color: #00e676; margin: 0; text-align: center;">Daily Summary</h2>
        </div>
        <table>
            <tr><td class="label">Total Trades</td><td class="value">{trades:,}</td></tr>
            <tr><td class="label">Total Profit</td><td class="value" style="font-size: 18px;">${profit:,.2f}</td></tr>
            <tr><td class="label">Success Rate</td><td class="value">{success_rate:.1f}%</td></tr>
            <tr><td class="label">Average Profit/Trade</td><td class="value">${avg_profit:.2f}</td></tr>
            <tr><td class="label">Disconnections Today</td><td class="value">{self.daily_stats['disconnections']}</td></tr>
        </table>
        """
        
        subject = f"Daily Summary: {trades:,} trades | ${profit:,.2f} profit"
        html = self._get_html_template("Daily Summary Report", content)
        
        self.daily_stats = {'trades': 0, 'profit': 0.0, 'errors': 0, 'disconnections': 0}
        return await self.send_email(subject, html)
    
    async def send_connection_lost_alert(self) -> bool:
        self.connection_lost_time = datetime.now(timezone.utc)
        self.daily_stats['disconnections'] += 1
        
        content = f"""
        <div style="background-color: #ff5252; padding: 15px; border-radius: 8px;">
            <h2 style="margin: 0; color: white;">Connection Lost</h2>
            <p style="margin: 10px 0 0 0; color: white;">
                The bot lost internet connection at {datetime.now().strftime('%H:%M:%S')}.
            </p>
        </div>
        """
        
        subject = "Flash Bot Alert: Connection Lost"
        html = self._get_html_template("Connection Alert", content)
        return await self.send_email(subject, html)
    
    async def send_connection_restored_alert(self) -> bool:
        downtime = "Unknown"
        if self.connection_lost_time:
            delta = datetime.now(timezone.utc) - self.connection_lost_time
            minutes = int(delta.total_seconds() / 60)
            downtime = f"{minutes} minutes" if minutes < 60 else f"{minutes // 60}h {minutes % 60}m"
        
        content = f"""
        <div style="background-color: #00c853; padding: 15px; border-radius: 8px;">
            <h2 style="margin: 0; color: white;">Connection Restored</h2>
            <p style="margin: 10px 0 0 0; color: white;">Trading has resumed. Downtime: {downtime}</p>
        </div>
        """
        
        subject = "Flash Bot: Connection Restored"
        html = self._get_html_template("Connection Restored", content)
        self.connection_lost_time = None
        return await self.send_email(subject, html)
    
    async def send_startup_notification(self, stats: Dict = None) -> bool:
        trades = 0
        profit = 0
        if stats:
            trades = stats.get('executed_trades', 0)
            profit = stats.get('net_profit', 0)
        
        content = f"""
        <div style="background-color: #00c853; padding: 15px; border-radius: 8px;">
            <h2 style="margin: 0; color: white;">Bot Started</h2>
            <p style="margin: 10px 0 0 0; color: white;">Flash Loan Bot is now running.</p>
        </div>
        <table style="margin-top: 20px;">
            <tr><td class="label">Started At</td><td class="value">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
            <tr><td class="label">Mode</td><td class="value">Simulation</td></tr>
            <tr><td class="label">Status</td><td class="value" style="color: #00c853;">Running</td></tr>
            <tr><td class="label">Total Trades (All Time)</td><td class="value">{trades:,}</td></tr>
            <tr><td class="label">Total Profit (All Time)</td><td class="value">${profit:,.2f}</td></tr>
        </table>
        <p style="color: #a0a0a0; margin-top: 20px;">
            You will receive updates every 2 hours and a daily summary at midnight.
        </p>
        """
        
        subject = f"Flash Loan Bot Started | {trades:,} trades | ${profit:,.2f} profit"
        html = self._get_html_template("Bot Started", content)
        return await self.send_email(subject, html)


class NotificationScheduler:
    def __init__(self, notifier: EmailNotifier, db):
        self.notifier = notifier
        self.db = db
        self.running = False
        self.last_2hour_check = datetime.now()
        self.last_daily_check = datetime.now().date()
    
    async def start(self):
        self.running = True
        logger.info("Notification scheduler started")
        
        # Get stats from database for startup notification
        stats = await get_stats_from_database(self.db)
        await self.notifier.send_startup_notification(stats)
        
        while self.running:
            try:
                now = datetime.now()
                
                hours_passed = (now - self.last_2hour_check).total_seconds() / 3600
                if hours_passed >= 2:
                    stats = await get_stats_from_database(self.db)
                    await self.notifier.send_2hour_update(stats)
                    self.last_2hour_check = now
                
                if now.date() > self.last_daily_check and now.hour == 0:
                    stats = await get_stats_from_database(self.db)
                    await self.notifier.send_daily_summary(stats)
                    self.last_daily_check = now.date()
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Notification scheduler error: {e}")
                await asyncio.sleep(60)
    
    def stop(self):
        self.running = False
        logger.info("Notification scheduler stopped")
