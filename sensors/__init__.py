"""Sensor ingestion package.
Provides a simple interface to convert raw sensor payloads into
:class:`PhysicalTrigger` objects used by the orchestrator.
"""

from .sensor_interface import PhysicalTrigger, ingest_payload
