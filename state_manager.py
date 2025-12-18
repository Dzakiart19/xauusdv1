import json
import os
import datetime
import logging

from config import BotConfig


logger = logging.getLogger("StateManager")


class StateManager:
    def __init__(self):
        self.user_states = {}
        self.subscribers = set()
        self.current_signal = {}
        self.last_signal_info = {}
    
    @staticmethod
    def get_default_user_state():
        return {
            'win_count': 0,
            'loss_count': 0,
            'be_count': 0,
            'active_trade': {},
            'tracking_message_id': None,
            'last_signal_time': None
        }
    
    def get_user_state(self, chat_id):
        chat_id = str(chat_id)
        if chat_id not in self.user_states:
            self.user_states[chat_id] = self.get_default_user_state()
        return self.user_states[chat_id]
    
    def save_user_states(self):
        try:
            states_to_save = {}
            for chat_id, state in self.user_states.items():
                state_copy = state.copy()
                if state_copy.get('active_trade') and 'start_time_utc' in state_copy['active_trade']:
                    trade = state_copy['active_trade'].copy()
                    if isinstance(trade.get('start_time_utc'), datetime.datetime):
                        trade['start_time_utc'] = trade['start_time_utc'].isoformat()
                    state_copy['active_trade'] = trade
                states_to_save[chat_id] = state_copy
            with open(BotConfig.USER_STATES_FILENAME, 'w') as f:
                json.dump(states_to_save, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user states: {e}")
    
    def load_user_states(self):
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
                        except:
                            pass
                    self.user_states[chat_id] = state
                logger.info(f"Loaded states for {len(self.user_states)} users")
        except Exception as e:
            logger.error(f"Failed to load user states: {e}")
    
    def save_subscribers(self):
        with open(BotConfig.SUBSCRIBERS_FILENAME, 'w') as f:
            json.dump(list(self.subscribers), f)
    
    def load_subscribers(self):
        try:
            if os.path.exists(BotConfig.SUBSCRIBERS_FILENAME):
                with open(BotConfig.SUBSCRIBERS_FILENAME, 'r') as f:
                    self.subscribers = set(json.load(f))
                logger.info(f"Loaded {len(self.subscribers)} subscribers")
        except Exception as e:
            logger.error(f"Failed to load subscribers: {e}")
    
    def add_subscriber(self, chat_id):
        chat_id = str(chat_id)
        self.subscribers.add(chat_id)
        self.save_subscribers()
    
    def remove_subscriber(self, chat_id):
        chat_id = str(chat_id)
        self.subscribers.discard(chat_id)
        self.save_subscribers()
    
    def is_subscriber(self, chat_id):
        return str(chat_id) in self.subscribers
    
    def reset_user_data(self, chat_id):
        chat_id = str(chat_id)
        user_state = self.get_user_state(chat_id)
        old_stats = f"W:{user_state['win_count']} L:{user_state['loss_count']} BE:{user_state['be_count']}"
        
        user_state['win_count'] = 0
        user_state['loss_count'] = 0
        user_state['be_count'] = 0
        user_state['active_trade'] = {}
        user_state['tracking_message_id'] = None
        
        self.save_user_states()
        return old_stats
    
    def update_trade_result(self, result_type):
        for cid in self.subscribers:
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
        self.save_user_states()
    
    def set_active_trade_for_subscribers(self, trade_info):
        for cid in self.subscribers:
            us = self.get_user_state(cid)
            us['active_trade'] = trade_info.copy()
            us['tracking_message_id'] = None
        self.save_user_states()
    
    def clear_user_tracking_messages(self):
        for chat_id in self.subscribers:
            user_state = self.get_user_state(chat_id)
            user_state['tracking_message_id'] = None
        self.save_user_states()
    
    def update_current_signal(self, signal_info):
        self.current_signal = signal_info
    
    def clear_current_signal(self):
        self.current_signal = {}
    
    def update_last_signal_info(self, info):
        self.last_signal_info.clear()
        self.last_signal_info.update(info)
