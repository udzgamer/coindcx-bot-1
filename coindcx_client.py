# coindcx_client.py
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode


class CoinDCXClient:
    BASE_URL = 'https://api.coindcx.com'

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def _generate_signature(self, params):
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _get_headers(self):
        return {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

    def get_markets(self):
        url = f"{self.BASE_URL}/exchange/v1/markets"
        response = requests.get(url, headers=self._get_headers())
        return response.json()

    def get_order_book(self, market):
        url = f"{self.BASE_URL}/exchange/v1/order_book"
        params = {'market': market}
        response = requests.get(url, headers=self._get_headers(), params=params)
        return response.json()

    def get_account_balance(self):
        url = f"{self.BASE_URL}/exchange/v1/account_balance"
        timestamp = int(time.time())
        params = {'timestamp': timestamp}
        signature = self._generate_signature(params)
        params['signature'] = signature
        response = requests.get(url, headers=self._get_headers(), params=params)
        return response.json()

    def place_order(self, market, side, order_type, price, quantity, stop_price=None):
        url = f"{self.BASE_URL}/exchange/v1/place_order"
        timestamp = int(time.time())
        params = {
            'market': market,
            'side': side,
            'type': order_type,
            'price': str(price),
            'quantity': str(quantity),
            'timestamp': timestamp
        }
        if stop_price:
            params['stop_price'] = str(stop_price)
        signature = self._generate_signature(params)
        params['signature'] = signature
        response = requests.post(url, headers=self._get_headers(), json=params)
        return response.json()

    def cancel_order(self, order_id):
        url = f"{self.BASE_URL}/exchange/v1/cancel_order"
        timestamp = int(time.time())
        params = {
            'order_id': order_id,
            'timestamp': timestamp
        }
        signature = self._generate_signature(params)
        params['signature'] = signature
        response = requests.post(url, headers=self._get_headers(), json=params)
        return response.json()

    def get_open_orders(self, market):
        url = f"{self.BASE_URL}/exchange/v1/open_orders"
        timestamp = int(time.time())
        params = {
            'market': market,
            'timestamp': timestamp
        }
        signature = self._generate_signature(params)
        params['signature'] = signature
        response = requests.get(url, headers=self._get_headers(), params=params)
        return response.json()

    def get_order_details(self, order_id):
        url = f"{self.BASE_URL}/exchange/v1/order_details"
        timestamp = int(time.time())
        params = {
            'order_id': order_id,
            'timestamp': timestamp
        }
        signature = self._generate_signature(params)
        params['signature'] = signature
        response = requests.get(url, headers=self._get_headers(), params=params)
        return response.json()