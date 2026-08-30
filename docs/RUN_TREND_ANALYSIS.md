# اجرای تحلیل زنده Strategy V2 با داده Nobitex

این ابزار داده واقعی OHLCV را از API عمومی Nobitex دریافت می‌کند و نتیجه تحلیل Strategy V2 را مستقیماً در ترمینال چاپ می‌کند. هیچ سفارشی ارسال نمی‌شود.

## اجرا

```bash
python run_trend_analysis.py --symbol BTCIRT --timeframe 15m --limit 800
```

نمونه برای اتریوم:

```bash
python run_trend_analysis.py --symbol ETHIRT --timeframe 15m --limit 800
```

نمادهای با قالب Nobitex نیز پذیرفته می‌شوند:

```bash
python run_trend_analysis.py --symbol btc-rls --timeframe 1H --limit 800
```

اگر مقدار سرمایه برای محاسبه Position Size داده شود:

```bash
python run_trend_analysis.py --symbol BTCIRT --timeframe 15m --limit 800 --equity 1000000000
```

## خروجی

برنامه موارد زیر را چاپ می‌کند:

1. وضعیت اتصال به Nobitex
2. تعداد کندل‌های دریافت‌شده در تایم‌فریم ورود، 4H و 1D
3. بازه زمانی داده‌ها
4. آخرین قیمت و حجم
5. تعداد Timestamp Gapها
6. EMA20
7. ATR14 و ATR percentage
8. وضعیت رژیم 4H و 1D
9. وضعیت Strategy V2
10. Direction، Entry، Stop Loss، TP1، TP2 و Risk/Reward در صورت وجود Setup
11. توضیح مرحله‌به‌مرحله علت صدور سیگنال

اگر شروط استراتژی کامل نباشند، برنامه به‌جای ساختن سیگنال مصنوعی، `NO_VALID_SETUP` نمایش می‌دهد.

## نکته مهم درباره داده

تحلیل با `use_cache=False` انجام می‌شود تا هر بار اجرای برنامه داده تازه از Nobitex درخواست شود. برای Backtest قابل تکرار باید از مسیر HistoricalData و CSV cache استفاده شود.

## نکته مهم درباره معامله

این ابزار فقط Research/Analysis است. هیچ endpoint مربوط به ثبت سفارش در آن استفاده نمی‌شود.
