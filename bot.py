# bot.py
import os
import time
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
from ta.volatility import AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice
from dotenv import load_dotenv
from coindcx_client import CoinDCXClient
from models import db, Config, BotStatus
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import db, BotStatus

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)

# CoinDCX API credentials
COINDCX_API_KEY = os.getenv('COINDCX_API_KEY')
COINDCX_API_SECRET = os.getenv('COINDCX_API_SECRET')

# Initialize CoinDCX Client
coindcx_client = CoinDCXClient(COINDCX_API_KEY, COINDCX_API_SECRET)

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

# Global Variables for SL and TSL
sl_order_id = None
tsl_triggered = False
highest_price = None
lowest_price = None


def get_current_time():
    return datetime.utcnow()


def is_within_session(current_time, config):
    session_start = current_time.replace(hour=config.session_start.hour, minute=config.session_start.minute,
                                        second=config.session_start.second, microsecond=0)
    session_end = session_start + timedelta(hours=21)  # 21 hours session
    # Handle session crossing midnight
    if session_end.day > session_start.day:
        if current_time >= session_start or current_time < session_end:
            return True
    else:
        if session_start <= current_time < session_end:
            return True
    return False


def fetch_market_data(symbol):
    try:
        order_book = coindcx_client.get_order_book(market=symbol)
        bids = order_book['bids']
        asks = order_book['asks']
        last_price = float(order_book['last_traded_price'])
        return last_price, bids, asks
    except Exception as e:
        logging.error(f"Error fetching market data: {e}")
        raise


def fetch_account_balance():
    try:
        balance = coindcx_client.get_account_balance()
        # Extract INR balance
        inr_balance = next((item for item in balance if item['currency'] == 'INR'), None)
        if inr_balance:
            return float(inr_balance['available_balance'])
        return 0.0
    except Exception as e:
        logging.error(f"Error fetching account balance: {e}")
        return 0.0


def place_order(market, side, order_type, price, quantity, stop_price=None):
    try:
        response = coindcx_client.place_order(
            market=market,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            stop_price=stop_price
        )
        if response.get('status') == 'success':
            order_id = response.get('data', {}).get('order_id')
            logging.info(f"Placed {side} {order_type} order: {order_id} at price {price}, quantity {quantity}")
            return order_id
        else:
            logging.error(f"Failed to place order: {response}")
            return None
    except Exception as e:
        logging.error(f"Error placing order: {e}")
        return None


def cancel_order(order_id):
    try:
        response = coindcx_client.cancel_order(order_id=order_id)
        if response.get('status') == 'success':
            logging.info(f"Cancelled order: {order_id}")
            return True
        else:
            logging.error(f"Failed to cancel order {order_id}: {response}")
            return False
    except Exception as e:
        logging.error(f"Error cancelling order {order_id}: {e}")
        return False


def get_open_orders(market):
    try:
        open_orders = coindcx_client.get_open_orders(market=market)
        return open_orders
    except Exception as e:
        logging.error(f"Error fetching open orders: {e}")
        return []


def get_order_details(order_id):
    try:
        order_details = coindcx_client.get_order_details(order_id=order_id)
        return order_details
    except Exception as e:
        logging.error(f"Error fetching order details for {order_id}: {e}")
        return None


def set_stop_loss_with_buffer(entry_price, side, quantity, buffer_amount):
    try:
        if side == 'buy':
            # For buy positions, SL is below the entry price
            stop_price = entry_price - config.sl_amount
            limit_price = stop_price - buffer_amount  # Buffer below stop price
            sl_side = 'sell'
        else:
            # For sell positions, SL is above the entry price
            stop_price = entry_price + config.sl_amount
            limit_price = stop_price + buffer_amount  # Buffer above stop price
            sl_side = 'buy'

        # Attempt to place Stop Limit order
        order_id = place_order(
            market=config.symbol,
            side=sl_side,
            order_type='stop-limit',
            price=limit_price,
            quantity=quantity,
            stop_price=stop_price
        )

        if order_id:
            logging.info(f"Stop Limit order placed: Order ID = {order_id}, Stop Price = {stop_price}, Limit Price = {limit_price}")
            return order_id
        else:
            logging.warning("Failed to place Stop Limit order. Retrying once.")
            # Retry once
            order_id = place_order(
                market=config.symbol,
                side=sl_side,
                order_type='stop-limit',
                price=limit_price,
                quantity=quantity,
                stop_price=stop_price
            )
            if order_id:
                logging.info(f"Stop Limit order placed on retry: Order ID = {order_id}, Stop Price = {stop_price}, Limit Price = {limit_price}")
                return order_id
            else:
                logging.warning("Failed to place Stop Limit order on retry. Placing Stop Market order.")
                # Place Stop Market order as fallback
                order_id = place_order(
                    market=config.symbol,
                    side=sl_side,
                    order_type='market',
                    price=None,  # Market order doesn't require price
                    quantity=quantity
                )
                if order_id:
                    logging.info(f"Stop Market order placed: Order ID = {order_id}")
                    return order_id
                else:
                    logging.error("Failed to place Stop Market order.")
                    return None
    except Exception as e:
        logging.error(f"Error setting stop-loss with buffer: {e}")
        return None


def main():
    global sl_order_id, tsl_triggered, highest_price, lowest_price

    highest_price = None
    lowest_price = None

    while True:
        try:
            # Fetch current config and bot status
            config = session.query(Config).first()
            status = session.query(BotStatus).first()

            if not status.running:
                time.sleep(5)
                continue

            SYMBOL = config.symbol
            SL_AMOUNT = config.sl_amount
            TSL_STEP = config.tsl_step
            TRADE_QUANTITY = config.trade_quantity  # In INR

            current_time = get_current_time()
            if is_within_session(current_time, config):
                last_price, bids, asks = fetch_market_data(SYMBOL)

                # Initialize highest and lowest price trackers
                if highest_price is None or last_price > highest_price:
                    highest_price = last_price
                if lowest_price is None or last_price < lowest_price:
                    lowest_price = last_price

                # Example Strategy: Simple Price Threshold
                BUY_THRESHOLD = 1000  # Example value; adjust as needed
                SELL_THRESHOLD = 2000  # Example value; adjust as needed

                open_orders = get_open_orders(SYMBOL)
                current_position = False  # Spot trading on CoinDCX doesn't track positions like futures

                # Example: Place Buy Order
                if last_price <= BUY_THRESHOLD and not open_orders:
                    order_id = place_order(
                        market=SYMBOL,
                        side='buy',
                        order_type='limit',
                        price=BUY_THRESHOLD,
                        quantity=TRADE_QUANTITY
                    )
                    if order_id:
                        sl_order_id = set_stop_loss_with_buffer(last_price, 'buy', TRADE_QUANTITY, buffer_amount=0.5)
                        tsl_triggered = False  # Reset TSL trigger

                # Example: Place Sell Order
                elif last_price >= SELL_THRESHOLD and not open_orders:
                    order_id = place_order(
                        market=SYMBOL,
                        side='sell',
                        order_type='limit',
                        price=SELL_THRESHOLD,
                        quantity=TRADE_QUANTITY
                    )
                    if order_id:
                        sl_order_id = set_stop_loss_with_buffer(last_price, 'sell', TRADE_QUANTITY, buffer_amount=0.5)
                        tsl_triggered = False  # Reset TSL trigger

                # Manage Trailing Stop Loss
                if sl_order_id:
                    order_details = get_order_details(sl_order_id)
                    if order_details and order_details.get('status') == 'executed':
                        logging.info(f"Stop loss order executed: {sl_order_id}")
                        sl_order_id = None  # Reset after execution
                        highest_price = None
                        lowest_price = None
                        tsl_triggered = False

                # Implement Trailing Stop Loss Logic
                # (This is a simplified example; adapt based on actual strategy)
                if sl_order_id and not tsl_triggered:
                    if config.symbol.startswith('BTC') or config.symbol.startswith('ETH'):
                        # For buy positions: adjust SL upwards as price increases
                        if last_price > highest_price:
                            new_stop_price = last_price - config.tsl_step
                            new_limit_price = new_stop_price - 0.5  # Buffer remains at $0.5
                            # Attempt to cancel existing SL order
                            if cancel_order(sl_order_id):
                                # Place new SL order with updated prices
                                new_order_id = set_stop_loss_with_buffer(last_price, 'buy', TRADE_QUANTITY, buffer_amount=0.5)
                                if new_order_id:
                                    sl_order_id = new_order_id
                                    tsl_triggered = True
                                    logging.info(f"Trailing Stop Loss updated: New SL Order ID = {sl_order_id}")
                    # Implement similar logic for sell positions if applicable

            else:
                # Outside trading session; cancel all open orders
                open_orders = get_open_orders(SYMBOL)
                for order in open_orders:
                    cancel_order(order['order_id'])

            # Sleep for a defined interval before next iteration
            time.sleep(60)  # Check every minute

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            time.sleep(5)  # Wait before retrying
            continue


if __name__ == "__main__":
    main()