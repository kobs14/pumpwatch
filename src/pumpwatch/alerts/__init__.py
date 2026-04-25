"""Alert engine package — Session 6.

Subscribes to ``pw:price.updated``, evaluates threshold + volume-spike
detectors per active subscription, dedupes via Redis TTL keys, persists
every fired alert, then dispatches via Telegram. All suppression
(mute / quiet-hours / ``PAUSED``) lives at dispatch time here, not in
the worker (ADR #15).
"""
