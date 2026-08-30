# Nobitex Smart Money Signal Engine

A Python-based cryptocurrency market analysis and signal generation engine designed for Nobitex markets using Smart Money Concepts (SMC) trading logic.

## Overview

`python_Nobitext_Signal_SmartMoney` is a modular trading analysis framework that separates market data collection, strategy logic, risk management, and backtesting.

The project is designed to generate structured trading signals from market data while keeping the core strategy independent from any future user interface such as Web dashboards, APIs, Telegram bots, or other automation layers.

## Features

- Smart Money / ICT inspired market analysis
- Nobitex market data integration
- Multi-timeframe analysis
- Signal generation with:
  - Entry zone
  - Stop loss
  - Take profit levels
  - Risk/Reward calculation
  - Confidence scoring
  - Signal explanation
- Market scanning and ranking
- Historical backtesting
- Performance evaluation
- Risk management module
- Terminal-based dashboard output

## Project Structure

```
.
├── backtest/              # Backtesting engine and performance analysis
├── data/                  # Historical and candle data management
├── exchange/              # Nobitex API communication
├── models/                # Data models for signals and setups
├── risk/                  # Risk management logic
├── strategy/              # Trading strategy engine
├── docs/                  # Documentation
├── config.py              # Application configuration
├── main.py                # CLI entry point
├── run_backtest_v2.py     # Backtest runner
└── requirements.txt       # Python dependencies
```

## Installation

Clone the repository:

```bash
git clone https://github.com/alies707/python_Nobitext_Signal_SmartMoney.git
cd python_Nobitext_Signal_SmartMoney
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate environment:

Linux/macOS:

```bash
source venv/bin/activate
```

Windows:

```powershell
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Configure API and strategy settings inside `config.py` or environment variables depending on your deployment method.

Never commit private API keys or sensitive credentials into the repository.

## Usage

### Analyze default market

```bash
python main.py
```

### Analyze a specific symbol

```bash
python main.py --symbol BTCIRT
```

### Analyze with custom timeframe

```bash
python main.py --symbol BTCIRT --timeframe 15m
```

### Scan markets

```bash
python main.py --scan
```

### Run backtest

```bash
python main.py --backtest
```

Example with symbol:

```bash
python main.py --backtest --symbol BTCIRT
```

## Signal Output

Generated signals include:

- Market direction (LONG / SHORT / NONE)
- Entry price
- Stop loss
- Take profit targets
- Risk to reward ratio
- Smart Money score
- Confidence level
- Strategy explanation

## Backtesting

The backtesting engine evaluates historical performance and provides metrics such as:

- Total trades
- Win rate
- Profit factor
- Average R multiple
- Total return
- Maximum drawdown
- Sharpe ratio

## Development Roadmap

Future improvements may include:

- Web dashboard
- REST API service
- Telegram notifications
- Live trading integration
- Advanced machine learning models
- Improved market structure detection

## Disclaimer

This project is for research and educational purposes only.

Cryptocurrency trading involves significant risk. Generated signals are analytical outputs and should not be considered financial advice.

## License

See repository license information for usage terms.
