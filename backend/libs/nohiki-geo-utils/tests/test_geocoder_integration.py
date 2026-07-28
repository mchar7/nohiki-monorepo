"""Nominatim response contracts with recorded transport fixtures and one live smoke."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

import nohiki_geo_utils.geocoder as geocoder_module
import pytest
from geopy.adapters import BaseAsyncAdapter
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location, LocationType
from nohiki_geo_utils.geocoder import build_geocode_query, geocode_location, geocode_query

type NominatimPayload = list[dict[str, str]]

COORDINATE_TOLERANCE = 0.05
RATE_LIMIT_DELAY = 1.5
NOMINATIM_SMOKE_ENV = "NOHIKI_RUN_NOMINATIM_SMOKE"

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module")
def recorded_nominatim_responses() -> Mapping[str, NominatimPayload]:
    """Return bounded Nominatim search responses recorded for contract queries."""
    return {
        "New York, NY, United States": [
            {
                "display_name": "New York, United States",
                "lat": "40.7127281",
                "lon": "-74.0060152",
            }
        ],
        "London, United Kingdom": [
            {
                "display_name": "London, Greater London, England, United Kingdom",
                "lat": "51.5074456",
                "lon": "-0.1277653",
            }
        ],
        "Toronto, Ontario, Canada": [
            {
                "display_name": "Toronto, Golden Horseshoe, Ontario, Canada",
                "lat": "43.6534817",
                "lon": "-79.3839347",
            }
        ],
        "Tokyo, Japan": [
            {
                "display_name": "Tokyo, Japan",
                "lat": "35.6768601",
                "lon": "139.7638947",
            }
        ],
        "Sydney, Australia": [
            {
                "display_name": "Sydney, Council of the City of Sydney, New South Wales, Australia",
                "lat": "-33.8698439",
                "lon": "151.2082848",
            }
        ],
        "Berlin, Germany": [
            {
                "display_name": "Berlin, Germany",
                "lat": "52.5173885",
                "lon": "13.3951309",
            }
        ],
        "San Francisco, California, United States": [
            {
                "display_name": "San Francisco, California, United States",
                "lat": "37.7792588",
                "lon": "-122.4193286",
            }
        ],
        "Amsterdam, Netherlands": [
            {
                "display_name": "Amsterdam, North Holland, Netherlands",
                "lat": "52.3730796",
                "lon": "4.8924534",
            }
        ],
        "Dublin, Ireland": [
            {
                "display_name": "Dublin, County Dublin, Ireland",
                "lat": "53.3493795",
                "lon": "-6.2605593",
            }
        ],
        "Seattle, Washington, United States": [
            {
                "display_name": "Seattle, King County, Washington, United States",
                "lat": "47.6038321",
                "lon": "-122.330062",
            }
        ],
        "Paris, France": [
            {
                "display_name": "Paris, Ile-de-France, France",
                "lat": "48.8588897",
                "lon": "2.320041",
            }
        ],
        "Xyzzy Nonexistent Place 12345": [],
        "Springfield, United States": [
            {
                "display_name": "Springfield, Sangamon County, Illinois, United States",
                "lat": "39.7990175",
                "lon": "-89.6439575",
            }
        ],
    }


class RecordedNominatimAdapter(BaseAsyncAdapter):
    """Serve recorded Nominatim JSON through GeoPy's async HTTP boundary."""

    def __init__(
        self,
        *,
        proxies: object,
        ssl_context: object,
        responses: Mapping[str, NominatimPayload],
    ) -> None:
        super().__init__(proxies=proxies, ssl_context=ssl_context)
        self._responses = responses

    async def get_json(
        self,
        url: str,
        *,
        timeout: float,  # noqa: ASYNC109 -- GeoPy's adapter protocol requires this keyword.
        headers: Mapping[str, str],
    ) -> NominatimPayload:
        """Return the fixture assigned to the request's exact query."""
        parsed_url = urlsplit(url)
        assert parsed_url.hostname == "nominatim.openstreetmap.org"
        assert timeout == 10
        assert headers["User-Agent"] == "nohiki-job-platform/1.0"

        query_values = parse_qs(parsed_url.query).get("q")
        assert query_values is not None
        assert len(query_values) == 1
        query = query_values[0]
        assert query in self._responses, f"Missing recorded Nominatim response for {query!r}"
        return self._responses[query]

    async def get_text(
        self,
        url: str,
        *,
        timeout: float,  # noqa: ASYNC109 -- GeoPy's adapter protocol requires this keyword.
        headers: Mapping[str, str],
    ) -> str:
        """Reject unrecorded text transport calls."""
        pytest.fail(f"Unexpected Nominatim text request: url={url!r}, timeout={timeout!r}, headers={headers!r}")


@pytest.fixture
def recorded_nominatim_transport(
    monkeypatch: pytest.MonkeyPatch,
    recorded_nominatim_responses: Mapping[str, NominatimPayload],
) -> None:
    """Inject the recorded adapter through Nominatim's adapter factory."""

    def adapter_factory(*, proxies: object, ssl_context: object) -> RecordedNominatimAdapter:
        return RecordedNominatimAdapter(
            proxies=proxies,
            ssl_context=ssl_context,
            responses=recorded_nominatim_responses,
        )

    monkeypatch.setattr(geocoder_module, "AioHTTPAdapter", adapter_factory)


@pytest.mark.usefixtures("recorded_nominatim_transport")
class TestRecordedNominatimContracts:
    """Coordinate and response contracts backed by bounded transport fixtures."""

    @pytest.mark.parametrize(
        ("query", "expected_latitude", "expected_longitude"),
        [
            ("New York, NY, United States", 40.7128, -74.0060),
            ("London, United Kingdom", 51.5074, -0.1278),
            ("Toronto, Ontario, Canada", 43.6532, -79.3832),
            ("Tokyo, Japan", 35.6764, 139.7640),
            ("Sydney, Australia", -33.8688, 151.2093),
            ("Berlin, Germany", 52.5170, 13.3889),
        ],
    )
    async def test_geocode_cities(
        self,
        query: str,
        expected_latitude: float,
        expected_longitude: float,
    ) -> None:
        """Recorded city responses produce accurate coordinates."""
        result = await geocode_query(query)

        assert result is not None, f"Failed to geocode: {query}"
        assert result.latitude == pytest.approx(expected_latitude, abs=COORDINATE_TOLERANCE)
        assert result.longitude == pytest.approx(expected_longitude, abs=COORDINATE_TOLERANCE)

    @pytest.mark.parametrize(
        ("location", "expected_latitude", "expected_longitude"),
        [
            (
                Location(
                    city="San Francisco",
                    state_province="California",
                    country=CountryCode.USA,
                    location_type=LocationType.PHYSICAL,
                ),
                37.7749,
                -122.4194,
            ),
            (
                Location(
                    city="Amsterdam",
                    country=CountryCode.NLD,
                    location_type=LocationType.PHYSICAL,
                ),
                52.3676,
                4.9041,
            ),
            (
                Location(
                    city="Dublin",
                    country=CountryCode.IRL,
                    location_type=LocationType.PHYSICAL,
                ),
                53.3498,
                -6.2603,
            ),
        ],
    )
    async def test_geocode_location_protos(
        self,
        location: Location,
        expected_latitude: float,
        expected_longitude: float,
    ) -> None:
        """Location protos retain their fields while gaining recorded coordinates."""
        result = await geocode_location(location)

        assert result.coordinates is not None, f"Failed to geocode: {location.city}"
        assert result.coordinates.latitude == pytest.approx(expected_latitude, abs=COORDINATE_TOLERANCE)
        assert result.coordinates.longitude == pytest.approx(expected_longitude, abs=COORDINATE_TOLERANCE)
        assert result.city == location.city
        assert result.country == location.country

    async def test_location_preserves_existing_coordinates(self) -> None:
        """Locations with existing coordinates remain unchanged."""
        original_coords = GeoCoordinates(latitude=40.0, longitude=-74.0)
        location = Location(
            city="Test City",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=original_coords,
        )

        result = await geocode_location(location)

        assert result.coordinates is not None
        assert result.coordinates.latitude == pytest.approx(40.0, abs=0.001)
        assert result.coordinates.longitude == pytest.approx(-74.0, abs=0.001)

    @pytest.mark.parametrize(
        ("location", "expected_query", "expected_latitude", "expected_longitude"),
        [
            (
                Location(
                    city="Seattle",
                    state_province="Washington",
                    country=CountryCode.USA,
                    location_type=LocationType.PHYSICAL,
                ),
                "Seattle, Washington, United States",
                47.6062,
                -122.3321,
            ),
            (
                Location(
                    city="Paris",
                    country=CountryCode.FRA,
                    location_type=LocationType.PHYSICAL,
                ),
                "Paris, France",
                48.8566,
                2.3522,
            ),
        ],
    )
    async def test_built_query_is_geocodable(
        self,
        location: Location,
        expected_query: str,
        expected_latitude: float,
        expected_longitude: float,
    ) -> None:
        """Built query strings resolve through recorded Nominatim responses."""
        query = build_geocode_query(location)
        assert query == expected_query

        result = await geocode_query(query)

        assert result is not None
        assert result.latitude == pytest.approx(expected_latitude, abs=COORDINATE_TOLERANCE)
        assert result.longitude == pytest.approx(expected_longitude, abs=COORDINATE_TOLERANCE)

    async def test_nonexistent_location_returns_none(self) -> None:
        """An empty recorded Nominatim response returns None."""
        result = await geocode_query("Xyzzy Nonexistent Place 12345")
        assert result is None

    async def test_ambiguous_city_still_geocodes(self) -> None:
        """An ambiguous recorded city result contains valid coordinates."""
        result = await geocode_query("Springfield, United States")

        assert result is not None
        assert -90 <= result.latitude <= 90
        assert -180 <= result.longitude <= 180


@pytest.mark.integration
@pytest.mark.slow
async def test_live_nominatim_smoke_is_rate_limited() -> None:
    """Verify one opt-in request against the public Nominatim service."""
    if os.environ.get(NOMINATIM_SMOKE_ENV) != "1":
        pytest.skip(f"Set {NOMINATIM_SMOKE_ENV}=1 to run the live Nominatim smoke test.")
    await asyncio.sleep(RATE_LIMIT_DELAY)

    result = await geocode_query("Berlin, Germany")

    assert result is not None
    assert result.latitude == pytest.approx(52.5170, abs=COORDINATE_TOLERANCE)
    assert result.longitude == pytest.approx(13.3889, abs=COORDINATE_TOLERANCE)
