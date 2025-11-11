import sys
import types
import importlib
from json import JSONDecodeError
from unittest.mock import patch
import pytest


class FakeLogger:
    """A simple fake logger to capture logs for assertions."""
    def __init__(self):
        self.info_messages = []
        self.debug_messages = []
        self.warning_messages = []
        self.error_messages = []

    def info(self, msg, *args, **kwargs):
        self.info_messages.append(str(msg))

    def debug(self, msg, *args, **kwargs):
        self.debug_messages.append(str(msg))

    def warning(self, msg, *args, **kwargs):
        self.warning_messages.append(str(msg))

    def error(self, msg, *args, **kwargs):
        self.error_messages.append(str(msg))


class FakeResponse:
    """A fake HTTP response with configurable JSON payload or exception."""
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def __repr__(self):
        return f"<FakeResponse payload={self._payload!r}>"


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch):
    """
    Set up fake modules for external dependencies so that dbgap_study_metadata
    can be imported in isolation.
    """
    # Create a single FakeLogger instance to be returned by get_logger
    fake_logger = FakeLogger()

    # cdislogging with get_logger
    cdislogging_mod = types.ModuleType("cdislogging")

    def get_logger(_name):
        return fake_logger

    cdislogging_mod.get_logger = get_logger

    # gen3 package and submodules
    gen3_mod = types.ModuleType("gen3")
    gen3_external_mod = types.ModuleType("gen3.external")

    class ExternalMetadataSourceInterface:
        def __init__(self, api, auth_provider=None):
            self.api = api
            self.auth_provider = auth_provider

    gen3_external_mod.ExternalMetadataSourceInterface = ExternalMetadataSourceInterface

    gen3_external_nih_mod = types.ModuleType("gen3.external.nih")
    gen3_external_nih_utils_mod = types.ModuleType("gen3.external.nih.utils")

    def default_get_dbgap_accession_as_parts(_phsid):
        raise NotImplementedError("Stub get_dbgap_accession_as_parts not configured")

    gen3_external_nih_utils_mod.get_dbgap_accession_as_parts = default_get_dbgap_accession_as_parts

    gen3_utils_mod = types.ModuleType("gen3.utils")

    def append_query_params(url, params):
        return url  # not used in code under test

    gen3_utils_mod.append_query_params = append_query_params

    # Inject all modules into sys.modules
    monkeypatch.setitem(sys.modules, "cdislogging", cdislogging_mod)
    monkeypatch.setitem(sys.modules, "gen3", gen3_mod)
    monkeypatch.setitem(sys.modules, "gen3.external", gen3_external_mod)
    monkeypatch.setitem(sys.modules, "gen3.external.nih", gen3_external_nih_mod)
    monkeypatch.setitem(sys.modules, "gen3.external.nih.utils", gen3_external_nih_utils_mod)
    monkeypatch.setitem(sys.modules, "gen3.utils", gen3_utils_mod)

    yield fake_logger


@pytest.fixture
def subject_module(fake_environment):
    """
    Import the module under test after setting up the fake environment.
    """
    # Ensure a clean import even if another test previously imported the module
    if "dbgap_study_metadata" in sys.modules:
        del sys.modules["dbgap_study_metadata"]
    mod = importlib.import_module("dbgap_study_metadata")
    return mod


@pytest.fixture
def subject_class(subject_module):
    """Return the dbgapStudyMetadata class from the subject module."""
    return subject_module.dbgapStudyMetadata


@pytest.fixture
def subject_instance(subject_class):
    """Create an instance of dbgapStudyMetadata with defaults."""
    return subject_class()


def test_dbgapStudyMetadata_init_defaults(subject_class):
    """Ensure default initialization sets API and auth_provider as expected."""
    sut = subject_class()
    assert sut.api == "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/"
    assert sut.auth_provider is None


def test_dbgapStudyMetadata_init_custom_values(subject_class):
    """Ensure custom API and auth_provider are passed to the base class."""
    api = "https://example.org/dbgap/api/v1/study_config/"
    auth = object()
    sut = subject_class(api=api, auth_provider=auth)
    assert sut.api == api
    assert sut.auth_provider is auth


def test_dbgapStudyMetadata_get_metadata_for_ids_happy_path(subject_module, subject_class):
    """Return aggregated study metadata for each provided ID."""
    sut = subject_class(api="https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/")

    ids = ["phs000001.v1", "phs000002.v2"]
    parts_map = {
        "phs000001.v1": {"phsid_number": "000001", "version_number": "1"},
        "phs000002.v2": {"phsid_number": "000002", "version_number": "2"},
    }

    def parts_side_effect(phsid):
        return parts_map[phsid]

    expected_urls = [
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000001.v1",
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000002.v2",
    ]
    responses = {
        expected_urls[0]: FakeResponse({"data": {"study_id": "phs000001.v1", "val": 1}}),
        expected_urls[1]: FakeResponse({"data": {"study_id": "phs000002.v2", "val": 2}}),
    }
    calls = []

    def mocked_get(url, *args, **kwargs):
        calls.append(url)
        return responses[url]

    with patch("dbgap_study_metadata.get_dbgap_accession_as_parts", side_effect=parts_side_effect):
        with patch("dbgap_study_metadata.requests.get", side_effect=mocked_get):
            out = sut.get_metadata_for_ids(ids)

    assert calls == expected_urls
    assert set(out.keys()) == set(ids)
    assert out["phs000001.v1"] == {"study_id": "phs000001.v1", "val": 1}
    assert out["phs000002.v2"] == {"study_id": "phs000002.v2", "val": 2}


def test_dbgapStudyMetadata_get_metadata_for_ids_warns_when_version_missing(subject_module, subject_class, fake_environment):
    """Log a warning and continue when version is not specified in ID parts."""
    sut = subject_class(api="https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/")

    phsid = "phs000007"  # given as input; parts will simulate missing version
    parts = {"phsid_number": "000007", "version_number": ""}

    expected_url = "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000007.v"
    response = FakeResponse({"data": {"study_id": phsid, "name": "Study 7"}})

    def mocked_get(url, *args, **kwargs):
        assert url == expected_url
        return response

    with patch("dbgap_study_metadata.get_dbgap_accession_as_parts", return_value=parts):
        with patch("dbgap_study_metadata.requests.get", side_effect=mocked_get):
            out = sut.get_metadata_for_ids([phsid])

    assert phsid in out
    assert out[phsid]["name"] == "Study 7"
    # Verify a warning was logged
    warnings = [m for m in fake_environment.warning_messages if "does not specify a version" in m]
    assert len(warnings) == 1


def test_dbgapStudyMetadata_get_metadata_for_ids_skips_when_no_data(subject_class):
    """Skip IDs when the response JSON does not contain 'data'."""
    sut = subject_class(api="https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/")
    ids = ["phs000010.v3"]

    parts = {"phsid_number": "000010", "version_number": "3"}
    expected_url = "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000010.v3"
    response = FakeResponse({"error": "not found"})

    with patch("dbgap_study_metadata.get_dbgap_accession_as_parts", return_value=parts):
        with patch("dbgap_study_metadata.requests.get", return_value=response):
            out = sut.get_metadata_for_ids(ids)

    assert out == {}  # skipped due to missing 'data'


def test_dbgapStudyMetadata_get_metadata_for_ids_json_decode_error_raises_due_to_missing_import(subject_class):
    """A JSON decode error triggers a NameError because JSONDecodeError is not imported in the module."""
    sut = subject_class(api="https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/")
    ids = ["phs000011.v1"]

    parts = {"phsid_number": "000011", "version_number": "1"}
    expected_url = "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000011.v1"
    response = FakeResponse(JSONDecodeError("Expecting value", "doc", 0))

    with patch("dbgap_study_metadata.get_dbgap_accession_as_parts", return_value=parts):
        with patch("dbgap_study_metadata.requests.get", return_value=response):
            with pytest.raises(NameError):
                sut.get_metadata_for_ids(ids)


def test_dbgapStudyMetadata_get_metadata_for_ids_empty_list_returns_empty(subject_class):
    """Return empty dict when given an empty list of IDs."""
    sut = subject_class()
    assert sut.get_metadata_for_ids([]) == {}


@pytest.mark.parametrize("bad_input", [None, 123, "not-a-list", {"id": "phs0001"}])
def test_dbgapStudyMetadata_get_metadata_for_ids_invalid_input_raises(subject_class, bad_input):
    """Invalid input types should raise a TypeError when iterated over."""
    sut = subject_class()
    with pytest.raises(TypeError):
        sut.get_metadata_for_ids(bad_input)


def test_dbgapStudyMetadata_get_metadata_for_ids_mixed_success_and_failure(subject_class):
    """Process multiple IDs, skipping those without usable 'data' field."""
    sut = subject_class(api="https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/")
    ids = ["phs000020.v1", "phs000021.v1", "phs000022.v3"]

    parts_map = {
        "phs000020.v1": {"phsid_number": "000020", "version_number": "1"},
        "phs000021.v1": {"phsid_number": "000021", "version_number": "1"},
        "phs000022.v3": {"phsid_number": "000022", "version_number": "3"},
    }

    def parts_side_effect(phsid):
        return parts_map[phsid]

    responses = {
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000020.v1": FakeResponse({"data": {"id": "ok-20"}}),
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000021.v1": FakeResponse({"error": "server error"}),
        "https://submit.ncbi.nlm.nih.gov/dbgap/api/v1/study_config/phs000022.v3": FakeResponse({"data": {"id": "ok-22"}}),
    }

    def mocked_get(url, *args, **kwargs):
        return responses[url]

    with patch("dbgap_study_metadata.get_dbgap_accession_as_parts", side_effect=parts_side_effect):
        with patch("dbgap_study_metadata.requests.get", side_effect=mocked_get):
            out = sut.get_metadata_for_ids(ids)

    assert set(out.keys()) == {"phs000020.v1", "phs000022.v3"}
    assert out["phs000020.v1"]["id"] == "ok-20"
    assert out["phs000022.v3"]["id"] == "ok-22"