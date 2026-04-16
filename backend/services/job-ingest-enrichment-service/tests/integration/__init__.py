"""Integration tests for job-ingest-enrichment-service.

This module contains integration tests that make real LLM calls
to verify the extraction and skill clarification pipelines work correctly.

Structure:
- fixtures/: Job listing fixtures and test data
- validators/: Output validation modules for each extraction concern
- test_extraction/: Tests for unified job extraction (run_extraction_agent)
- test_skill_clarification/: Tests for skill clarification service
"""
