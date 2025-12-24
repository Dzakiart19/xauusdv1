import json
import os
import datetime
import logging
from typing import Optional, Any, Union

from config import BotConfig


logger = logging.getLogger("StateManager")


class StateManager:
    def __init__(self):
        self.user_states: dict[str, dict] = {}
        self.subscribers: set[str] = set()
        self.current_signal: dict = {}
        self.last_signal_info: dict = {}
        self.current_indicators: dict = {}  # Real-time RSI, EMA, ADX
        self.strategy_status: dict = {}  # Current strategy status
        self.signal_history: list[dict] = []
        self._load_signal_history()
    
    @staticmethod
    def get_default_user_state() -> dict:
        return {
            'win_count': 0,
            'loss_count': 0,
            'be_count': 0,
            'active_trade': {},
            'tracking_message_id': None,
            'last_signal_time': None,
            'signal_history': []
        }
    
    def get_user_state(self, chat_id: str | int) -> dict:
        chat_id = str(chat_id)
        if chat_id not in self.user_states:
            self.user_states[chat_id] = self.get_default_user_state()
        return self.user_states[chat_id]
    
    def save_user_states(self) -> None:
        try:
            states_to_save = {}
            for chat_id, state in self.user_states.items():
                state_copy = state.copy()
                if state_copy.get('active_trade') and 'start_time_utc' in state_copy['active_trade']:
                    trade = state_copy['active_trade'].copy()
                    if isinstance(trade.get('start_time_utc'), datetime.datetime):
                        trade['start_time_utc'] = trade['start_time_utc'].isoformat()
                    state_copy['active_trade'] = trade
                # Ensure signal_history timestamps are serialized
                if state_copy.get('signal_history'):
                    sig_history = []
                    for sig in state_copy['signal_history']:
                        sig_copy = sig.copy()
                        if isinstance(sig_copy.get('timestamp'), datetime.datetime):
                            sig_copy['timestamp'] = sig_copy['timestamp'].isoformat()
                        if isinstance(sig_copy.get('closed_at'), datetime.datetime):
                            sig_copy['closed_at'] = sig_copy['closed_at'].isoformat()
                        sig_history.append(sig_copy)
                    state_copy['signal_history'] = sig_history
                states_to_save[chat_id] = state_copy
            
            temp_file = f"{BotConfig.USER_STATES_FILENAME}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(states_to_save, f, indent=2)
            os.replace(temp_file, BotConfig.USER_STATES_FILENAME)
        except Exception as e:
            logger.error(f"Failed to save user states: {e}")
    
    def load_user_states(self) -> None:
        try:
            if os.path.exists(BotConfig.USER_STATES_FILENAME):
                with open(BotConfig.USER_STATES_FILENAME, 'r') as f:
                    loaded = json.load(f)
                for chat_id, state in loaded.items():
                    if state.get('active_trade') and 'start_time_utc' in state['active_trade']:
                        try:
                            state['active_trade']['start_time_utc'] = datetime.datetime.fromisoformat(
                                state['active_trade']['start_time_utc']
                            )
                        except (ValueError, TypeError):
                            pass
                    # Migration: ensure signal_history field exists
                    if 'signal_history' not in state:
                        state['signal_history'] = []
                    self.user_states[chat_id] = state
                logger.info(f"Loaded states for {len(self.user_states)} users")
        except Exception as e:
            logger.error(f"Failed to load user states: {e}")
    
    def save_subscribers(self) -> None:
        try:
            temp_file = f"{BotConfig.SUBSCRIBERS_FILENAME}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(list(self.subscribers), f)
            os.replace(temp_file, BotConfig.SUBSCRIBERS_FILENAME)
        except Exception as e:
            logger.error(f"Failed to save subscribers: {e}")
    
    def load_subscribers(self) -> None:
        try:
            if os.path.exists(BotConfig.SUBSCRIBERS_FILENAME):
                with open(BotConfig.SUBSCRIBERS_FILENAME, 'r') as f:
                    self.subscribers = set(json.load(f))
                logger.info(f"Loaded {len(self.subscribers)} subscribers")
        except Exception as e:
            logger.error(f"Failed to load subscribers: {e}")
    
    def add_subscriber(self, chat_id: str | int) -> None:
        chat_id = str(chat_id)
        self.subscribers.add(chat_id)
        self.save_subscribers()
    
    def remove_subscriber(self, chat_id: str | int) -> None:
        chat_id = str(chat_id)
        self.subscribers.discard(chat_id)
        self.save_subscribers()
    
    def is_subscriber(self, chat_id: str | int) -> bool:
        return str(chat_id) in self.subscribers
    
    def reset_user_data(self, chat_id: str | int) -> str:
        chat_id = str(chat_id)
        user_state = self.get_user_state(chat_id)
        old_stats = f"W:{user_state['win_count']} L:{user_state['loss_count']} BE:{user_state['be_count']}"
        
        user_state['win_count'] = 0
        user_state['loss_count'] = 0
        user_state['be_count'] = 0
        user_state['active_trade'] = {}
        user_state['tracking_message_id'] = None
        user_state['signal_history'] = []
        
        self.save_user_states()
        
        return old_stats
    
    def update_trade_result(self, result_type: str, chat_id: Optional[Union[str, int]] = None) -> None:
        # If specific chat_id provided, update only that user; otherwise update all
        cids_to_update = [str(chat_id)] if chat_id else self.subscribers
        
        for cid in cids_to_update:
            us = self.get_user_state(cid)
            if us.get('active_trade'):
                if result_type == 'WIN':
                    us['win_count'] += 1
                elif result_type == 'LOSS':
                    us['loss_count'] += 1
                elif result_type == 'BREAK_EVEN':
                    us['be_count'] += 1
                us['active_trade'] = {}
                us['tracking_message_id'] = None
                
                # Update last signal in user's signal history
                if us.get('signal_history'):
                    us['signal_history'][-1]['result'] = result_type
                    us['signal_history'][-1]['closed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.save_user_states()
    
    def set_active_trade_for_subscribers(self, trade_info: dict) -> None:
        for cid in self.subscribers:
            us = self.get_user_state(cid)
            us['active_trade'] = trade_info.copy()
            us['tracking_message_id'] = None
            
            # Add signal to user's signal history
            signal_entry = {
                'id': len(us.get('signal_history', [])) + 1,
                'direction': trade_info.get('direction'),
                'entry_price': trade_info.get('entry_price'),
                'tp1': trade_info.get('tp1_level'),
                'tp2': trade_info.get('tp2_level'),
                'sl': trade_info.get('sl_level'),
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'result': 'PENDING'
            }
            if 'signal_history' not in us:
                us['signal_history'] = []
            us['signal_history'].append(signal_entry)
            if len(us['signal_history']) > 500:
                us['signal_history'] = us['signal_history'][-500:]
        self.save_user_states()
    
    def clear_user_tracking_messages(self) -> None:
        for chat_id in self.subscribers:
            user_state = self.get_user_state(chat_id)
            user_state['tracking_message_id'] = None
        self.save_user_states()
    
    def update_current_signal(self, signal_info: dict) -> None:
        self.current_signal = signal_info
    
    def update_current_indicators(self, rsi: float, ema: float, adx: float) -> None:
        """Store current indicator values for real-time display"""
        self.current_indicators = {
            'rsi': rsi,
            'ema': ema,
            'adx': adx,
            'timestamp': datetime.datetime.now(datetime.timezone.utc)
        }
    
    def update_strategy_status(self, status_info: dict) -> None:
        """Update strategy status from signal engine"""
        self.strategy_status = status_info
    
    def determine_strategy_status(self, price: float, rsi: float, prev_rsi: float, ema: float, adx: float) -> dict:
        """Determine current strategy status based on market conditions"""
        status_key = "TREND WEAK"
        status_display = "⚠️ NO TRADE — Trend Lemah (ADX < 25)"
        condition_text = f"Trend lemah / sideways — ADX: {adx:.1f}"
        emoji = "⚠️"
        
        if adx > 25:  # ADX threshold = 25 (same as filter)
            has_active_position = bool(getattr(self, 'current_signal', {}))
            
            if has_active_position:
                status_key = "POSITION ACTIVE"
                status_display = "🔥 POSITION ACTIVE"
                condition_text = "Ada sinyal aktif yang dipantau TP / SL"
                emoji = "🔥"
            else:
                price_above_ema = price > ema
                price_below_ema = price < ema
                
                rsi_oversold = rsi < 30
                rsi_overbought = rsi > 70
                prev_rsi_oversold = prev_rsi < 30
                prev_rsi_overbought = prev_rsi > 70
                
                # BUY SETUP: Price > EMA, RSI exiting oversold, ADX strong
                if price_above_ema:
                    if prev_rsi_oversold and rsi >= 30 and rsi > prev_rsi:
                        status_key = "BUY SETUP"
                        status_display = "🟢 BUY SETUP (Bullish Trend Valid)"
                        condition_text = "Pullback selesai — menunggu trigger BUY"
                        emoji = "🟢"
                    else:
                        status_key = "WAITING PULLBACK"
                        status_display = "⏳ WAITING PULLBACK"
                        condition_text = "Bullish tapi RSI belum oversold — menunggu koreksi"
                        emoji = "⏳"
                
                # SELL SETUP: Price < EMA, RSI exiting overbought, ADX strong
                elif price_below_ema:
                    if prev_rsi_overbought and rsi <= 70 and rsi < prev_rsi:
                        status_key = "SELL SETUP"
                        status_display = "🔴 SELL SETUP (Bearish Trend Valid)"
                        condition_text = "Momentum turun — menunggu trigger SELL"
                        emoji = "🔴"
                    else:
                        status_key = "WAITING PULLBACK"
                        status_display = "⏳ WAITING PULLBACK"
                        condition_text = "Bearish tapi RSI belum overbought — menunggu koreksi"
                        emoji = "⏳"
                else:
                    # Price = EMA
                    status_key = "WAITING PULLBACK"
                    status_display = "⏳ WAITING PULLBACK"
                    condition_text = "Harga = EMA — menunggu break direction"
                    emoji = "⏳"
        
        return {
            'key': status_key,
            'display': status_display,
            'condition': condition_text,
            'emoji': emoji
        }
    
    def clear_current_signal(self) -> None:
        self.current_signal = {}
    
    def update_last_signal_info(self, info: dict) -> None:
        self.last_signal_info.clear()
        self.last_signal_info.update(info)
    
    def _load_signal_history(self) -> None:
        try:
            if os.path.exists(BotConfig.SIGNAL_HISTORY_FILENAME):
                with open(BotConfig.SIGNAL_HISTORY_FILENAME, 'r') as f:
                    self.signal_history = json.load(f)
                logger.info(f"Loaded {len(self.signal_history)} signals from history")
        except Exception as e:
            logger.error(f"Failed to load signal history: {e}")
            self.signal_history = []
    
    def save_signal_history(self) -> None:
        try:
            temp_file = f"{BotConfig.SIGNAL_HISTORY_FILENAME}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(self.signal_history[-500:], f, indent=2)
            os.replace(temp_file, BotConfig.SIGNAL_HISTORY_FILENAME)
        except Exception as e:
            logger.error(f"Failed to save signal history: {e}")
    
    def add_signal_to_history(self, signal_info: dict) -> None:
        entry = {
            'id': len(self.signal_history) + 1,
            'direction': signal_info.get('direction'),
            'entry_price': signal_info.get('entry_price'),
            'tp1': signal_info.get('tp1_level'),
            'tp2': signal_info.get('tp2_level'),
            'sl': signal_info.get('sl_level'),
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'result': 'PENDING'
        }
        self.signal_history.append(entry)
        if len(self.signal_history) > 500:
            self.signal_history = self.signal_history[-500:]
        self.save_signal_history()
    
    def update_last_signal_result(self, result: str) -> None:
        if self.signal_history:
            self.signal_history[-1]['result'] = result
            self.signal_history[-1]['closed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.save_signal_history()
    
    def get_trade_stats(self) -> dict:
        total_wins = 0
        total_losses = 0
        total_be = 0
        
        for chat_id in self.subscribers:
            us = self.get_user_state(chat_id)
            total_wins += us.get('win_count', 0)
            total_losses += us.get('loss_count', 0)
            total_be += us.get('be_count', 0)
        
        total_trades = total_wins + total_losses + total_be
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        return {
            'wins': total_wins,
            'losses': total_losses,
            'break_evens': total_be,
            'total_trades': total_trades,
            'win_rate': round(win_rate, 1)
        }
    
    def get_today_stats(self, chat_id: Optional[str | int] = None) -> dict:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        
        # If chat_id provided, get per-user stats; otherwise global
        if chat_id:
            chat_id = str(chat_id)
            user_state = self.get_user_state(chat_id)
            today_signals = [s for s in user_state.get('signal_history', [])
                            if datetime.datetime.fromisoformat(s['timestamp']).date() == today]
        else:
            today_signals = [s for s in self.signal_history 
                            if datetime.datetime.fromisoformat(s['timestamp']).date() == today]
        
        wins = sum(1 for s in today_signals if s.get('result') == 'WIN')
        losses = sum(1 for s in today_signals if s.get('result') == 'LOSS')
        be = sum(1 for s in today_signals if s.get('result') == 'BREAK_EVEN')
        pending = sum(1 for s in today_signals if s.get('result') == 'PENDING')
        
        return {
            'total': len(today_signals),
            'wins': wins,
            'losses': losses,
            'break_evens': be,
            'pending': pending,
            'win_rate': round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0, 1)
        }
