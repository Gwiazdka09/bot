"""Footstats scrapers package."""
from footstats.scrapers.football_data import APIClient
from footstats.scrapers.api_football import APIFootball
from footstats.scrapers.bzzoiro import BzzoiroClient
from footstats.scrapers.source_manager import SourceManager

__all__ = ["APIClient", "APIFootball", "BzzoiroClient", "SourceManager"]
