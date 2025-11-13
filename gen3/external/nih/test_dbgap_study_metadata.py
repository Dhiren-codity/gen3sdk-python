import sys
import types
from unittest.mock import Mock, call
import pytest


@pytest.fixture(autouse=True)
def stub_external_dependencies(monkeypatch):
    """Stub external modules and dependencies required by dbgap_study_metadata.py before import."""
    # Create stub modules
    gen3 = types.ModuleType("gen3")
    gen3_external = types.ModuleType("gen3.external")
    gen3_external_nih = types.ModuleType("gen3.external.nih")
    gen3_external_nih_utils = types.ModuleType("gen3.external.nih.utils")
    gen3_utils = types.ModuleType("gen3.utils")
    cdislogging = types.ModuleType("cdislogging")

    # Stub ExternalMetadataSourceInterface
    class ExternalMetadataSourceInterface:
        def __init__(self, api, auth_provider=None):
            self.api = api
            self.auth_provider = auth_provider

    # Stub get_dbgap_accession_as_parts (will be patched in tests as needed)
    def get_dbgap_accession_as_parts(_):
        return {"phsid_number": "000000", "version_number": "1"}

    # Stub append_query_params (not used directly here)
    def append_query_params(url, params):
        return url

    # Stub get_logger to return a simple object with logging methods
    class DummyLogger:
        def info(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    def get_logger(_):
        return DummyLogger()

    # Assign stubs to modules
    gen3_external.ExternalMetadataSourceInterface = ExternalMetadataSourceInterface
    gen3_external_nih_utils.get_dbgap_accession_as_parts = get_dbgap_accession_as_parts
    gen3_utils.append_query_params = append_query_params
    cdislogging.get_logger = get_logger

    # Register modules in sys.modules
    monkeypatch.setitem(sys.modules, "gen3", gen3)
    monkeypatch.setitem(sys.modules, "gen3.external", gen3_external)
    monkeypatch.setitem(sys.modules, "gen3.external.nih", gen3_external_nih)
    monkeypatch.setitem(sys.modules, "gen3.external.nih.utils", gen3_external_nih_utils)
    monkeypatch.setitem(sys.modules, "gen3.utils", gen3_utils)
    monkeypatch.setitem(sys.modules, "cdislogging", cdislogging)


@pytest.fixture
def metadata_class():
    """Import and return the dbgapStudyMetadata class."""
    from dbgap_study_metadata import dbgapStudyMetadata

    return dbgapStudyMetadata


@pytest.fixture
def instance(metadata_class):
    """Create an instance of dbgapStudyMetadata with default configuration."""
    return metadata_class()


def test_dbgapStudyMetadata_init_defaults(metadata_class):
    """Test that initialization sets default API and auth_provider."""
    obj = metadata_class()
    assert (
        obj.api == "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/"
    )
    assert getattr(obj, "auth_provider", None) is None


def test_dbgapStudyMetadata_init_custom_api(metadata_class):
    """Test that initialization accepts and sets a custom API URL."""
    custom_api = "https://example.com/custom/"
    obj = metadata_class(api=custom_api)
    assert obj.api == custom_api


def test_dbgapStudyMetadata_get_metadata_for_ids_success_multiple(instance, monkeypatch):
    """Test get_metadata_for_ids returns metadata for multiple valid ids."""
    import dbgap_study_metadata as module

    # Patch logging to a Mock to observe calls (not strictly required)
    mock_logger = Mock()
    monkeypatch.setattr(module, "logging", mock_logger, raising=False)

    # Mock parsing of accessions
    parsed_parts = [
        {"phsid_number": "000007", "version_number": "32"},
        {"phsid_number": "000179", "version_number": "1"},
    ]
    monkeypatch.setattr(
        module, "get_dbgap_accession_as_parts", Mock(side_effect=parsed_parts)
    )

    # Prepare mock responses
    r1 = Mock()
    r1.json.return_value = {"data": {"id": "study-one"}}
    r2 = Mock()
    r2.json.return_value = {"data": {"id": "study-two"}}

    mock_get = Mock(side_effect=[r1, r2])
    monkeypatch.setattr(module.requests, "get", mock_get)

    ids = ["phs000007.v32", "phs000179.v1.p1.c1"]
    result = instance.get_metadata_for_ids(ids)

    assert result == {
        "phs000007.v32": {"id": "study-one"},
        "phs000179.v1.p1.c1": {"id": "study-two"},
    }

    expected_urls = [
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000007.v32",
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000179.v1",
    ]
    assert [c.args[0] for c in mock_get.call_args_list] == expected_urls


def test_dbgapStudyMetadata_get_metadata_for_ids_missing_version_logs_warning_and_builds_url(instance, monkeypatch):
    """Test behavior when version number is missing: logs warning and constructs URL accordingly."""
    import dbgap_study_metadata as module

    # Patch logging to a Mock
    mock_logger = Mock()
    monkeypatch.setattr(module, "logging", mock_logger, raising=False)

    # Mock accession parsing to return None version
    monkeypatch.setattr(
        module,
        "get_dbgap_accession_as_parts",
        Mock(return_value={"phsid_number": "123456", "version_number": None}),
    )

    # Mock request/response
    r = Mock()
    r.json.return_value = {"data": {"ok": True}}
    mock_get = Mock(return_value=r)
    monkeypatch.setattr(module.requests, "get", mock_get)

    ids = ["phs123456"]
    result = instance.get_metadata_for_ids(ids)

    # Ensure warning logged about missing version
    assert any(
        "does not specify a version" in str(args[0])
        for (args, kwargs) in (call.args, call.kwargs) and [call]
        for call in mock_logger.warning.mock_calls
    )

    # URL should contain "vNone" since version_number is None in f-string
    expected_url = (
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs123456.vNone"
    )
    mock_get.assert_called_once_with(expected_url)

    assert result == {"phs123456": {"ok": True}}


def test_dbgapStudyMetadata_get_metadata_for_ids_no_data_logs_error_and_skips(instance, monkeypatch):
    """Test that when response has no 'data', it logs error and skips that id."""
    import dbgap_study_metadata as module

    # Patch logging to a Mock
    mock_logger = Mock()
    monkeypatch.setattr(module, "logging", mock_logger, raising=False)

    # Mock accession parsing
    monkeypatch.setattr(
        module,
        "get_dbgap_accession_as_parts",
        Mock(return_value={"phsid_number": "654321", "version_number": "5"}),
    )

    # Mock response where "data" is missing/None and an error is present
    response_payload = {"data": None, "error": "Not found"}
    r = Mock()
    r.json.return_value = response_payload
    mock_get = Mock(return_value=r)
    monkeypatch.setattr(module.requests, "get", mock_get)

    ids = ["phs654321.v5"]
    result = instance.get_metadata_for_ids(ids)

    # Should log error and return empty result
    assert result == {}

    # Ensure error log mentions inability to get metadata for the id
    assert any(
        "Could not get metadata for phs654321.v5" in str(args[0])
        for (args, kwargs) in (call.args, call.kwargs) and [call]
        for call in mock_logger.error.mock_calls
    )


def test_dbgapStudyMetadata_get_metadata_for_ids_json_decode_error_skips_and_logs(instance, monkeypatch, capsys):
    """Test that a JSON decode error is handled by logging and skipping the id."""
    import dbgap_study_metadata as module

    # Patch in a JSONDecodeError class into the module so the except clause resolves
    class FakeJSONDecodeError(Exception):
        pass

    monkeypatch.setattr(module, "JSONDecodeError", FakeJSONDecodeError, raising=False)

    # Patch logging to a Mock
    mock_logger = Mock()
    monkeypatch.setattr(module, "logging", mock_logger, raising=False)

    # Mock accession parsing
    monkeypatch.setattr(
        module,
        "get_dbgap_accession_as_parts",
        Mock(return_value={"phsid_number": "777777", "version_number": "1"}),
    )

    # Mock response.json to raise the fake JSON decode error
    r = Mock()
    r.json.side_effect = FakeJSONDecodeError("bad json")
    mock_get = Mock(return_value=r)
    monkeypatch.setattr(module.requests, "get", mock_get)

    ids = ["phs777777.v1"]
    result = instance.get_metadata_for_ids(ids)

    # Verify it skipped the id and returned empty result
    assert result == {}

    # Verify it printed a message to stdout
    captured = capsys.readouterr()
    assert "Response could not be serialized" in captured.out

    # Verify error was logged
    assert mock_logger.error.called


def test_dbgapStudyMetadata_get_metadata_for_ids_empty_input_returns_empty(instance, monkeypatch):
    """Test that providing an empty list of ids returns an empty dict and makes no HTTP calls."""
    import dbgap_study_metadata as module

    # Monitor requests.get
    mock_get = Mock()
    monkeypatch.setattr(module.requests, "get", mock_get)

    result = instance.get_metadata_for_ids([])

    assert result == {}
    mock_get.assert_not_called()