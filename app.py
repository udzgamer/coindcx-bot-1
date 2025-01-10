# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, time
import os
import logging
from models import db, ConfigModel, BotStatus

# Initialize Flask app
app = Flask(__name__)

# Configure Flask app
app.secret_key = os.getenv('SECRET_KEY', 'your_default_secret_key')  # Use a strong secret key in production

# Handle 'postgres://' prefix by replacing it with 'postgresql://'
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///local.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database and migration
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Logging configuration
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
)

# Define Models
class ConfigModel(db.Model):
    __tablename__ = 'config'
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, default='BTCINR')
    session_start = db.Column(db.Time, nullable=False, default=time(8, 0, 0))
    session_end = db.Column(db.Time, nullable=False, default=time(5, 0, 0))
    sl_amount = db.Column(db.Float, nullable=False, default=25.0)
    tsl_step = db.Column(db.Float, nullable=False, default=10.0)
    trade_quantity = db.Column(db.Float, nullable=False, default=1000.0)

class BotStatus(db.Model):
    __tablename__ = 'bot_status'
    id = db.Column(db.Integer, primary_key=True)
    running = db.Column(db.Boolean, nullable=False, default=False)

# Initialize the database and create tables if they don't exist
with app.app_context():
    db.create_all()
    # Initialize Config and BotStatus if not present
    if ConfigModel.query.first() is None:
        config = ConfigModel()
        db.session.add(config)
        db.session.commit()
    if BotStatus.query.first() is None:
        status = BotStatus(running=False)
        db.session.add(status)
        db.session.commit()

# Initialize CoinDCX Client
from coindcx_client import CoinDCXClient
COINDCX_API_KEY = os.getenv('COINDCX_API_KEY')
COINDCX_API_SECRET = os.getenv('COINDCX_API_SECRET')
if not COINDCX_API_KEY or not COINDCX_API_SECRET:
    logging.error("CoinDCX API credentials are missing.")
    raise Exception("CoinDCX API credentials are not set.")

coindcx_client = CoinDCXClient(COINDCX_API_KEY, COINDCX_API_SECRET)

# Define Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    config = ConfigModel.query.first()
    status = BotStatus.query.first()
    symbols = []

    # Fetch all available spot market symbols from CoinDCX
    try:
        markets = coindcx_client.get_markets()
        symbols = [market['market'] for market in markets if market['status'] == 'active']
    except Exception as e:
        logging.error(f"Error fetching symbols from CoinDCX: {e}")
        flash('Error fetching symbols from CoinDCX. Please try again later.', 'danger')

    if request.method == 'POST':
        # Update Config
        selected_symbol = request.form.get('symbol', '').upper()
        if selected_symbol:
            config.symbol = selected_symbol

        try:
            session_start = datetime.strptime(request.form.get('session_start'), '%H:%M').time()
            session_end = datetime.strptime(request.form.get('session_end'), '%H:%M').time()
            config.session_start = session_start
            config.session_end = session_end
        except ValueError:
            flash('Invalid time format. Use HH:MM (24-hour).', 'danger')
            return redirect(url_for('index'))

        try:
            config.sl_amount = float(request.form.get('sl_amount', 25.0))
            config.tsl_step = float(request.form.get('tsl_step', 10.0))
            config.trade_quantity = float(request.form.get('trade_quantity', 1000.0))
        except ValueError:
            flash('SL, TSL steps, and Trade Quantity must be numeric.', 'danger')
            return redirect(url_for('index'))

        db.session.commit()
        flash('Configuration updated successfully.', 'success')
        return redirect(url_for('index'))

    return render_template('index.html', config=config, status=status, symbols=symbols)

@app.route('/start', methods=['POST'])
def start_bot():
    status = BotStatus.query.first()
    if not status.running:
        status.running = True
        db.session.commit()
        flash('Bot started.', 'success')
    else:
        flash('Bot is already running.', 'warning')
    return redirect(url_for('index'))

@app.route('/stop', methods=['POST'])
def stop_bot():
    status = BotStatus.query.first()
    if status.running:
        status.running = False
        db.session.commit()
        flash('Bot stopped.', 'success')
    else:
        flash('Bot is not running.', 'warning')
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)