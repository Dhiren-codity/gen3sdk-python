import sys
import types
import re
import pytest
from unittest.mock import Mock, patch

# ---- Prepare stubbed external dependencies before importing the module under test ----

# Stub cdislogging.get_logger
cdislogging = types.ModuleType("cdislogging")


class DummyLogger:
    def __init__(self):
        self.info = Mock()
        self.debug = Mock()
        self.warning = Mock()
        self.error = Mock()


def get_logger(_name):
    return DummyLogger()


cdislogging.get_logger = get_logger
sys.modules["cdislogging"] = cdislogging

# Stub gen3.external and utils
gen3 = types.ModuleType("gen3")

gen3_external = types.ModuleType("gen3.external")


class ExternalMetadataSourceInterface:
    def __init__(self, api, auth_provider):
        self.api = api
        self.auth_provider = auth_provider


gen3_external.ExternalMetadataSourceInterface = ExternalMetadataSourceInterface

gen3_external_nih = types.ModuleType("gen3.external.nih")
gen3_external_nih_utils = types.ModuleType("gen3.external.nih.utils")


def stub_get_dbgap_accession_as_parts(phsid):
    m = re.match(r"^phs(\d+)(?:\.v(\d+))?", phsid)
    phsid_number = m.group(1) if m else ""
    version = m.group(2) if (m and m.group(2)) else ""
    return {"phsid_number": phsid_number, "version_number": version}


gen3_external_nih_utils.get_dbgap_accession_as_parts = stub_get_dbgap_accession_as_parts

gen3_utils = types.ModuleType("gen3.utils")


def append_query_params(url, params):
    return url


gen3_utils.append_query_params = append_query_params

# Register package/module hierarchy
gen3.external = gen3_external
sys.modules["gen3"] = gen3

gen3_external.nih = gen3_external_nih
sys.modules["gen3.external"] = gen3_external

gen3_external_nih.utils = gen3_external_nih_utils
sys.modules["gen3.external.nih"] = gen3_external_nih
sys.modules["gen3.external.nih.utils"] = gen3_external_nih_utils

sys.modules["gen3.utils"] = gen3_utils

# ---- Import the class under test using the required import path ----
from dbgap_study_metadata import dbgapStudyMetadata


@pytest.fixture
def study_instance():
    """Create dbgapStudyMetadata instance with default configuration."""
    return dbgapStudyMetadata()


def test_dbgapStudyMetadata___init___defaults():
    """Ensure default initialization sets expected attributes."""
    obj = dbgapStudyMetadata()
    assert obj.api == "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/"
    assert getattr(obj, "auth_provider", None) is None


def test_dbgapStudyMetadata___init___custom():
    """Ensure custom initialization respects provided api and auth provider."""
    auth = object()
    api = "https://example.org/custom/base"
    obj = dbgapStudyMetadata(api=api, auth_provider=auth)
    assert obj.api == api
    assert obj.auth_provider is auth


def test_dbgapStudyMetadata_get_metadata_for_ids_single_success(study_instance):
    """Fetch metadata for a single valid study id."""
    phs = "phs000007.v32"
    expected_url = "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000007.v32"

    mock_resp = Mock()
    mock_resp.json = Mock(return_value={"data": {"id": phs, "name": "Study A"}})

    with patch("dbgap_study_metadata.requests.get", return_value=mock_resp) as mock_get:
        result = study_instance.get_metadata_for_ids([phs])

    assert result == {phs: {"id": phs, "name": "Study A"}}
    mock_get.assert_called_once_with(expected_url)


def test_dbgapStudyMetadata_get_metadata_for_ids_multiple_success(study_instance):
    """Fetch metadata for multiple valid study ids."""
    phs1 = "phs000007.v32"
    phs2 = "phs000179.v1.p1.c1"

    def mk_resp(data):
        r = Mock()
        r.json = Mock(return_value=data)
        return r

    def side_effect(url):
        if url.endswith("/phs000007.v32"):
            return mk_resp({"data": {"id": phs1, "name": "Study A"}})
        if url.endswith("/phs000179.v1"):
            return mk_resp({"data": {"id": "phs000179.v1", "name": "Study B"}})
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("dbgap_study_metadata.requests.get", side_effect=side_effect) as mock_get:
        result = study_instance.get_metadata_for_ids([phs1, phs2])

    assert result[phs1]["id"] == phs1
    assert result[phs2]["id"] == "phs000179.v1"
    assert mock_get.call_count == 2
    called_urls = [args[0] for args, _ in mock_get.call_args_list]
    assert called_urls[0].endswith("/phs000007.v32")
    assert called_urls[1].endswith("/phs000179.v1")


def test_dbgapStudyMetadata_get_metadata_for_ids_missing_version_logs_warning(study_instance):
    """When version is missing, it logs a warning and continues to fetch."""
    phs = "phs123456"
    # With stubbed parser, this will result in URL ending with '.v'
    expected_suffix = "/phs123456.v"

    mock_resp = Mock()
    mock_resp.json = Mock(return_value={"data": {"id": phs, "name": "NoVersion Study"}})

    with patch("dbgap_study_metadata.requests.get", return_value=mock_resp) as mock_get, patch(
        "dbgap_study_metadata.logging"
    ) as mock_logging:
        result = study_instance.get_metadata_for_ids([phs])

    assert result == {phs: {"id": phs, "name": "NoVersion Study"}}
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0].endswith(expected_suffix)
    assert mock_logging.warning.called is True


def test_dbgapStudyMetadata_get_metadata_for_ids_json_decode_error_handled(study_instance):
    """If response.json raises JSONDecodeError, method logs error and skips id."""
    module = sys.modules["dbgap_study_metadata"]

    class FakeJSONDecodeError(Exception):
        pass

    module.JSONDecodeError = FakeJSONDecodeError

    mock_resp = Mock()
    mock_resp.json = Mock(side_effect=FakeJSONDecodeError("bad json"))

    with patch("dbgap_study_metadata.requests.get", return_value=mock_resp), patch(
        "dbgap_study_metadata.logging"
    ) as mock_logging:
        result = study_instance.get_metadata_for_ids(["phs000001.v1"])

    assert result == {}
    assert mock_logging.error.called is True


def test_dbgapStudyMetadata_get_metadata_for_ids_no_data_error_field_logged(study_instance):
    """If response has no 'data' but has 'error', method logs error and skips id."""
    mock_resp = Mock()
    mock_resp.json = Mock(return_value={"error": "Not Found"})

    with patch("dbgap_study_metadata.requests.get", return_value=mock_resp), patch(
        "dbgap_study_metadata.logging"
    ) as mock_logging:
        result = study_instance.get_metadata_for_ids(["phs999999.v1"])

    assert result == {}
    assert mock_logging.error.called is True


def test_dbgapStudyMetadata_get_metadata_for_ids_requests_exception_propagates(study_instance):
    """Network errors from requests.get propagate to the caller."""
    with patch("dbgap_study_metadata.requests.get", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            study_instance.get_metadata_for_ids(["phs000001.v1"])


def test_dbgapStudyMetadata_get_metadata_for_ids_custom_api_base():
    """Ensure request URL is constructed correctly when custom base API is provided."""
    obj = dbgapStudyMetadata(api="https://example.com/base")
    mock_resp = Mock()
    mock_resp.json = Mock(return_value={"data": {"id": "phs000010.v2"}})

    with patch("dbgap_study_metadata.requests.get", return_value=mock_resp) as mock_get:
        res = obj.get_metadata_for_ids(["phs000010.v2"])

    assert res == {"phs000010.v2": {"id": "phs000010.v2"}}
    mock_get.assert_called_once_with("https://example.com/base/phs000010.v2")