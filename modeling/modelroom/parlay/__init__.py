"""Parlay pricing support (TEST, Moose 2026-11-27): historical correlation table and calibration backtest.

Nothing here changes a model, a shadow, a ledger or a projection. It reads stored box scores and stored ledger
probabilities and writes aggregate statistics (correlation coefficients with sample sizes) for the site's joint
probability engine.
"""
