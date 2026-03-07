"""Tests for GlossaryAgent."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.config import settings


def test_glossary_path_property():
    """settings.glossary_path returns outputs/glossary."""
    assert settings.glossary_path == settings.output_dir / "glossary"
