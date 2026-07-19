"""File ingest package (document pipeline + unified engine).

Keep this module lightweight: ``audit.health`` imports ``ingest.sync_index``
via package init during model-router startup — do not import adapters here.
"""
