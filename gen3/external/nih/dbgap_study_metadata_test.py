"""
Auto-generated tests using LLM and RAG
"""

from dbgapStudyMetadata import dbgapStudyMetadata

from unittest.mock import patch, MagicMock
import pytest



import pytest

def test_generation_failed():
    """Test generation produced unfixable syntax errors - placeholder only."""
    pytest.skip("Generated test had syntax errors that could not be fixed after all attempts")



import pytest
from unittest.mock import patch, MagicMock
from dbgapStudyMetadata import dbgapStudyMetadata

@pytest.fixture
def dbgap_study_metadata():
    return dbgapStudyMetadata()

@patch('dbgapStudyMetadata.requests.get')
@pytest.mark.parametrize("ids, mock_response, expected", [
    (["phs000001.v1"], {"data": {"study": "metadata"}}, {"phs000001.v1": {"study": "metadata"}}),
    (["phs000002.v1"], {"error": "Not found"}, {}),
    (["phs000003"], {"data": {"study": "metadata"}}, {"phs000003": {"study": "metadata"}}),
])

def test_get_metadata_for_ids(mock_get, dbgap_study_metadata, ids, mock_response, expected):
    mock_get.return_value.json.return_value = mock_response
    result = dbgap_study_metadata.get_metadata_for_ids(ids)
    assert result == expected
@patch('dbgapStudyMetadata.requests.get')

def test_get_metadata_for_ids_json_decode_error(mock_get, dbgap_study_metadata):
    mock_get.return_value.json.side_effect = JSONDecodeError("Expecting value", "", 0)
    result = dbgap_study_metadata.get_metadata_for_ids(["phs000004.v1"])
    assert result == {}
@patch('dbgapStudyMetadata.requests.get')

def test_get_metadata_for_ids_no_version_warning(mock_get, dbgap_study_metadata, caplog):
    mock_get.return_value.json.return_value = {"data": {"study": "metadata"}}
    dbgap_study_metadata.get_metadata_for_ids(["phs000005"])
    assert "does not specify a version" in caplog.text

