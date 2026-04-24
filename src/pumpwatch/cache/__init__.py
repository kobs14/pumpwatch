"""Redis client + pub-sub helpers owned by Session 5.

Imports from this package are the only code that should talk to Redis
directly. Other services (scheduler, workers, alerts) use the helpers
defined here so the key and channel conventions stay centralized.
"""
