"""Shared pytest fixtures for AI Employee tests."""

import pytest


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault structure for testing."""
    # Required top-level directories
    for folder in (
        "Needs_Action",
        "Plans",
        "Pending_Approval",
        "Approved",
        "Rejected",
        "Done",
        "Logs",
        "Briefings",
        "Accounting",
        "Drop",
        ".state",
    ):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)

    return tmp_path
