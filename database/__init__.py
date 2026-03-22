"""SQLite database layer for WBS Housing Bot."""
from .db import (
    init_db, make_hash, is_seen, mark_seen, bulk_is_seen,
    save_listing, get_recent_listings, get_listings_count, get_seen_count,
    record_source_result, get_source_stats, set_source_disabled, get_disabled_sources,
    log_event, get_recent_events, get_daily_summary,
)

__all__ = [
    "init_db", "make_hash", "is_seen", "mark_seen", "bulk_is_seen",
    "save_listing", "get_recent_listings", "get_listings_count", "get_seen_count",
    "record_source_result", "get_source_stats", "set_source_disabled", "get_disabled_sources",
    "log_event", "get_recent_events", "get_daily_summary",
]
