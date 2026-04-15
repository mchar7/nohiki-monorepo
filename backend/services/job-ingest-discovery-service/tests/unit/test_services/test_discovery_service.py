"""Unit tests for discovery_service module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from job_ingest_discovery_service.core.models import (
    DiscoveryLocation,
    DiscoveryRequest,
    DiscoveryResult,
    RawListing,
)
from job_ingest_discovery_service.providers.jobspy.provider import JobSpyProvider
from job_ingest_discovery_service.services.discovery_service import (
    _build_discovery_request,
    _clear_fallback_state,
    _compute_listing_hash,
    _dedupe_and_publish,
    _discover_from_all_sources,
    _discover_from_source,
    _filter_sources,
    _get_cache,
    _get_provider_config,
    _get_provider_config_map,
    _make_fallback_key,
    _map_location,
    _publish_listing,
    _record_error,
    _request_for_single_source,
    _should_fallback,
    _try_provider,
    run_discovery,
)
from nohiki.common.v1 import (
    CountryCode,
    JobBoardSource,
    LocationType,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import IngestionQuery


class TestFilterSources:
    """Tests for _filter_sources helper."""

    def test_filters_unspecified(self) -> None:
        """Removes UNSPECIFIED sources."""
        result = _filter_sources([JobBoardSource.UNSPECIFIED, JobBoardSource.INDEED])
        assert result == [JobBoardSource.INDEED]

    def test_filters_unsupported(self) -> None:
        """Removes unsupported sources."""
        result = _filter_sources([JobBoardSource.INDEED])
        assert result == [JobBoardSource.INDEED]

    def test_empty_list(self) -> None:
        """Returns empty for empty input."""
        assert _filter_sources([]) == []


class TestMapLocation:
    """Tests for _map_location helper."""

    def test_maps_remote_location(self) -> None:
        """Maps remote location correctly."""
        from nohiki.common.v1 import Location as ProtoLocation

        loc = ProtoLocation(
            city="",
            state_province="",
            country=CountryCode.USA,
            location_type=LocationType.REMOTE,
        )
        result = _map_location(loc)
        assert result.is_remote is True
        assert result.country == CountryCode.USA

    def test_maps_physical_location(self) -> None:
        """Maps physical location with city and region."""
        from nohiki.common.v1 import Location as ProtoLocation

        loc = ProtoLocation(
            city="Toronto",
            state_province="ON",
            country=CountryCode.CAN,
            location_type=LocationType.PHYSICAL,
        )
        result = _map_location(loc)
        assert result.city == "Toronto"
        assert result.region == "ON"
        assert result.is_remote is False


class TestBuildDiscoveryRequest:
    """Tests for _build_discovery_request helper."""

    def test_defaults_sources_when_empty(self) -> None:
        """Defaults to INDEED + LINKEDIN when no sources provided."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[],
            results_wanted=0,
        )
        result = _build_discovery_request(query)
        assert JobBoardSource.INDEED in result.sources
        assert JobBoardSource.LINKEDIN in result.sources

    def test_defaults_results_wanted(self) -> None:
        """Defaults to 50 when results_wanted is 0."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[JobBoardSource.INDEED],
            results_wanted=0,
        )
        result = _build_discovery_request(query)
        assert result.results_per_source > 0

    def test_filters_unspecified_work_arrangements(self) -> None:
        """Filters out UNSPECIFIED work arrangements."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[JobBoardSource.INDEED],
            work_arrangements=[WorkArrangement.UNSPECIFIED, WorkArrangement.REMOTE],
        )
        result = _build_discovery_request(query)
        assert WorkArrangement.UNSPECIFIED not in result.work_arrangements
        assert WorkArrangement.REMOTE in result.work_arrangements


class TestRequestForSingleSource:
    """Tests for _request_for_single_source helper."""

    def test_creates_single_source_request(self) -> None:
        """Creates request targeting single source."""
        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED, JobBoardSource.LINKEDIN),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )
        result = _request_for_single_source(request, JobBoardSource.INDEED)
        assert result.sources == (JobBoardSource.INDEED,)
        assert result.query_id == "q-1"


class TestMakeFallbackKey:
    """Tests for _make_fallback_key helper."""

    def test_builds_key(self) -> None:
        """Builds Redis key with provider and source."""
        key = _make_fallback_key("jobspy", JobBoardSource.INDEED)
        assert "provider_fallback" in key
        assert "jobspy" in key
        assert "INDEED" in key


class TestComputeListingHash:
    """Tests for _compute_listing_hash helper."""

    def test_computes_hash(self) -> None:
        """Computes SHA-256 hash from listing content."""
        listing = MagicMock(spec=RawListing)
        listing.title = "Software Engineer"
        listing.company = "Test Corp"
        listing.description = "Build things"

        result = _compute_listing_hash(listing)
        assert isinstance(result, str)
        assert len(result) == 64


class TestTryProvider:
    """Tests for _try_provider helper."""

    @pytest.mark.asyncio
    async def test_returns_listings_on_success(self) -> None:
        """Returns listings when provider succeeds."""
        provider = MagicMock()
        provider.name = "test-provider"
        provider.discover = AsyncMock(
            return_value=DiscoveryResult(
                listings=[MagicMock()],
                provider_name="test-provider",
                error=None,
                duration_seconds=1.0,
            )
        )

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._get_provider_config",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._clear_fallback_state",
                new_callable=AsyncMock,
            ),
        ):
            result = await _try_provider(provider, request, JobBoardSource.INDEED)
            assert result is not None
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_none_on_fallback(self) -> None:
        """Returns None when provider fails and should fallback."""
        provider = MagicMock()
        provider.name = "test-provider"
        provider.discover = AsyncMock(
            return_value=DiscoveryResult(
                listings=[],
                provider_name="test-provider",
                error="timeout",
                duration_seconds=5.0,
            )
        )

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._get_provider_config",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._should_fallback",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await _try_provider(provider, request, JobBoardSource.INDEED)
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_fallback(self) -> None:
        """Returns empty list when provider fails but no fallback."""
        provider = MagicMock()
        provider.name = "test-provider"
        provider.discover = AsyncMock(
            return_value=DiscoveryResult(
                listings=[],
                provider_name="test-provider",
                error="timeout",
                duration_seconds=5.0,
            )
        )

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._get_provider_config",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._should_fallback",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await _try_provider(provider, request, JobBoardSource.INDEED)
            assert result == []


class TestShouldFallback:
    """Tests for _should_fallback helper."""

    @pytest.mark.asyncio
    async def test_returns_false_when_disabled(self) -> None:
        """Returns False when fallback is disabled."""
        config = MagicMock()
        config.fallback.enabled = False
        result_obj = MagicMock()

        result = await _should_fallback("provider", JobBoardSource.INDEED, result_obj, config)
        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limited_above_threshold(self) -> None:
        """Returns True when rate limited above threshold."""
        config = MagicMock()
        config.fallback.enabled = True
        config.fallback.rate_limit_wait_threshold_seconds = 30

        result_obj = MagicMock()
        result_obj.error_code = "rate_limited"
        result_obj.retry_after_seconds = 60

        result = await _should_fallback("provider", JobBoardSource.INDEED, result_obj, config)
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_limited_below_threshold(self) -> None:
        """Returns False when rate limited below threshold."""
        config = MagicMock()
        config.fallback.enabled = True
        config.fallback.rate_limit_wait_threshold_seconds = 30

        result_obj = MagicMock()
        result_obj.error_code = "rate_limited"
        result_obj.retry_after_seconds = 10

        result = await _should_fallback("provider", JobBoardSource.INDEED, result_obj, config)
        assert result is False


class TestDiscoverFromSource:
    """Tests for _discover_from_source helper."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_providers(self) -> None:
        """Returns empty list when no providers registered for source."""
        registry = MagicMock()
        registry.get_providers_for_source.return_value = []

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        result = await _discover_from_source(registry, request, JobBoardSource.INDEED)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_listings_from_first_successful_provider(self) -> None:
        """Returns listings from first provider that succeeds."""
        mock_listing = MagicMock()
        provider = MagicMock()
        provider.name = "test"

        registry = MagicMock()
        registry.get_providers_for_source.return_value = [provider]

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with patch(
            "job_ingest_discovery_service.services.discovery_service._try_provider",
            new_callable=AsyncMock,
            return_value=[mock_listing],
        ):
            result = await _discover_from_source(registry, request, JobBoardSource.INDEED)
            assert len(result) == 1


class TestDiscoverFromAllSources:
    """Tests for _discover_from_all_sources helper."""

    @pytest.mark.asyncio
    async def test_single_source_no_gather(self) -> None:
        """Single source calls _discover_from_source directly."""
        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_provider_registry",
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._discover_from_source",
                new_callable=AsyncMock,
                return_value=[MagicMock()],
            ) as mock_discover,
        ):
            result = await _discover_from_all_sources(request)
            assert len(result) == 1
            mock_discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_sources_uses_taskgroup(self) -> None:
        """Multiple sources uses asyncio.TaskGroup."""
        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED, JobBoardSource.LINKEDIN),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_provider_registry",
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._discover_from_source",
                new_callable=AsyncMock,
                return_value=[MagicMock()],
            ),
        ):
            result = await _discover_from_all_sources(request)
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_nested_sources_and_parameters_share_leaf_limit(self) -> None:
        """Every blocking JobSpy leaf shares the command's configured limit."""
        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python", "rust"),
            sources=(JobBoardSource.INDEED, JobBoardSource.LINKEDIN),
            locations=(DiscoveryLocation(city="San Francisco", country=CountryCode.USA),),
            work_arrangements=(),
            results_per_source=50,
        )
        settings = MagicMock()
        settings.discovery.max_concurrent = 2
        settings.discovery.timeout_seconds = 30
        registry = MagicMock()
        registry.get_providers_for_source.side_effect = lambda _source: [JobSpyProvider()]
        active = 0
        max_active = 0
        leaf_calls = 0

        async def fake_to_thread(*_args: object, **_kwargs: object) -> pd.DataFrame:
            nonlocal active, max_active, leaf_calls
            active += 1
            leaf_calls += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            active -= 1
            return pd.DataFrame()

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_settings",
                return_value=settings,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_provider_registry",
                return_value=registry,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._clear_fallback_state",
                new_callable=AsyncMock,
            ),
            patch(
                "job_ingest_discovery_service.providers.jobspy.provider.asyncio.to_thread",
                side_effect=fake_to_thread,
            ),
        ):
            result = await _discover_from_all_sources(request)

        assert result == []
        assert leaf_calls == 8
        assert max_active == settings.discovery.max_concurrent
        assert max_active <= 2


class TestDedupeAndPublish:
    """Tests for at-least-once listing delivery."""

    @staticmethod
    def _listing() -> MagicMock:
        listing = MagicMock(spec=RawListing)
        listing.title = "Engineer"
        listing.company = "Corp"
        listing.description = "Build"
        listing.listing_url = "https://example.com/1"
        return listing

    @pytest.mark.asyncio
    async def test_successful_publish_is_marked_after_delivery(self) -> None:
        """A successful Kafka publish commits its Redis dedup marker afterward."""
        events: list[str] = []
        dedup = MagicMock()
        dedup.is_duplicate = AsyncMock(return_value=False)

        async def mark_seen(_key: str) -> None:
            events.append("mark")

        async def publish(*_args: object) -> None:
            events.append("publish")

        dedup.mark_seen = AsyncMock(side_effect=mark_seen)
        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_dedup_service",
                return_value=dedup,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._publish_listing",
                new_callable=AsyncMock,
                side_effect=publish,
            ),
        ):
            result = await _dedupe_and_publish([self._listing()], "q-1", "d-1")

        assert result == 1
        assert events == ["publish", "mark"]

    @pytest.mark.asyncio
    async def test_publish_failure_propagates_without_dedup_mark(self) -> None:
        """An unpublished observation remains eligible for command replay."""
        dedup = MagicMock()
        dedup.is_duplicate = AsyncMock(return_value=False)
        dedup.mark_seen = AsyncMock()

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_dedup_service",
                return_value=dedup,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._publish_listing",
                new_callable=AsyncMock,
                side_effect=RuntimeError("kafka down"),
            ),
            pytest.raises(RuntimeError, match="kafka down"),
        ):
            await _dedupe_and_publish([self._listing()], "q-1", "d-1")

        dedup.mark_seen.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_cancel_sibling_delivery(self) -> None:
        """Concurrent fan-out settles every listing before propagating a failure."""
        first = self._listing()
        second = self._listing()
        second.description = "Different"
        dedup = MagicMock()
        dedup.is_duplicate = AsyncMock(return_value=False)
        dedup.mark_seen = AsyncMock()

        async def publish(
            listing: RawListing,
            _content_hash: str,
            _query_id: str,
            _discovery_id: str,
        ) -> None:
            if listing is first:
                message = "kafka down"
                raise RuntimeError(message)

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_dedup_service",
                return_value=dedup,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._publish_listing",
                new_callable=AsyncMock,
                side_effect=publish,
            ) as publish_mock,
            pytest.raises(RuntimeError, match="kafka down"),
        ):
            await _dedupe_and_publish([first, second], "q-1", "d-1")

        assert publish_mock.await_count == 2
        dedup.mark_seen.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_redelivery_remains_bounded(self) -> None:
        """One host publishes identical listings once and Redis bounds later replay."""
        seen: set[str] = set()
        dedup = MagicMock()

        async def is_duplicate(key: str) -> bool:
            return key in seen

        async def mark_seen(key: str) -> None:
            seen.add(key)

        dedup.is_duplicate = AsyncMock(side_effect=is_duplicate)
        dedup.mark_seen = AsyncMock(side_effect=mark_seen)
        listing = self._listing()

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_dedup_service",
                return_value=dedup,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._publish_listing",
                new_callable=AsyncMock,
            ) as publish,
        ):
            assert await _dedupe_and_publish([listing, listing], "q-1", "d-1") == 1
            assert await _dedupe_and_publish([listing], "q-1", "d-1") == 0

        publish.assert_awaited_once()


class TestPublishListing:
    """Tests for _publish_listing helper."""

    @pytest.mark.asyncio
    async def test_publishes_successfully(self) -> None:
        """Publishes successfully."""
        listing = MagicMock(spec=RawListing)
        listing.title = "Engineer"
        listing.company = "Corp"
        listing.description = "Build"
        listing.listing_url = "https://example.com/1"
        listing.source = JobBoardSource.INDEED
        listing.external_id = "ext-1"
        listing.location_raw = "NYC"
        listing.compensation = ""
        listing.raw_skills = []
        listing.apply_url = ""
        listing.company_url = ""
        listing.posted_at = None

        with (
            patch("job_ingest_discovery_service.services.discovery_service.kafka_client") as mock_kafka,
            patch(
                "job_ingest_discovery_service.services.discovery_service.to_discovered_listing",
                return_value=MagicMock(
                    listing_url="https://example.com/1",
                    external_id="ext-1",
                    source=JobBoardSource.INDEED,
                ),
            ),
        ):
            mock_kafka.publish = AsyncMock()
            await _publish_listing(listing, "abc123", "q-1", "d-1")
            mock_kafka.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_propagates_publish_exception(self) -> None:
        """Propagates Kafka failure so the discovery command can be replayed."""
        listing = MagicMock(spec=RawListing)
        listing.listing_url = "https://example.com/1"

        with (
            patch("job_ingest_discovery_service.services.discovery_service.kafka_client") as mock_kafka,
            patch(
                "job_ingest_discovery_service.services.discovery_service.to_discovered_listing",
                return_value=MagicMock(
                    listing_url="https://example.com/1",
                    external_id="ext-1",
                    source=JobBoardSource.INDEED,
                ),
            ),
        ):
            mock_kafka.publish = AsyncMock(side_effect=RuntimeError("kafka down"))
            with pytest.raises(RuntimeError, match="kafka down"):
                await _publish_listing(listing, "abc123", "q-1", "d-1")


class TestGetCache:
    """Tests for _get_cache helper."""

    def test_returns_redis_cache(self) -> None:
        """Returns a RedisCache instance."""
        _get_cache.cache_clear()
        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_settings",
                return_value=MagicMock(
                    service_name="test-service",
                    redis=MagicMock(connection_string="redis://localhost:6379/0"),
                ),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service.create_cache",
                return_value=MagicMock(),
            ) as mock_create,
        ):
            result = _get_cache()
            assert result is not None
            mock_create.assert_called_once_with("test-service", redis_url="redis://localhost:6379/0")
        _get_cache.cache_clear()


class TestGetProviderConfigMap:
    """Tests for _get_provider_config_map helper."""

    def test_returns_dict_keyed_by_name(self) -> None:
        """Returns provider configs as dict keyed by name."""
        from job_ingest_discovery_service.core.config import ProviderConfigSettings

        _get_provider_config_map.cache_clear()
        mock_cfg = ProviderConfigSettings(name="jobspy")
        with patch(
            "job_ingest_discovery_service.services.discovery_service.get_settings",
            return_value=MagicMock(provider_registry=MagicMock(providers=[mock_cfg])),
        ):
            result = _get_provider_config_map()
            assert "jobspy" in result
            assert result["jobspy"] is mock_cfg
        _get_provider_config_map.cache_clear()


class TestGetProviderConfig:
    """Tests for _get_provider_config helper."""

    def test_returns_config_from_settings(self) -> None:
        """Returns config when provider exists in settings."""
        from job_ingest_discovery_service.core.config import ProviderConfigSettings

        mock_cfg = ProviderConfigSettings(name="jobspy")
        provider = MagicMock()
        provider.name = "jobspy"

        with patch(
            "job_ingest_discovery_service.services.discovery_service._get_provider_config_map",
            return_value={"jobspy": mock_cfg},
        ):
            result = _get_provider_config(provider)
            assert result is mock_cfg

    def test_falls_back_to_provider_defaults(self) -> None:
        """Returns default config when provider not in settings."""
        from job_ingest_discovery_service.core.config import ProviderFallbackSettings

        provider = MagicMock()
        provider.name = "unknown-provider"
        provider.default_enabled.return_value = True
        provider.default_priority.return_value = 50
        provider.default_fallback_settings.return_value = ProviderFallbackSettings()

        with patch(
            "job_ingest_discovery_service.services.discovery_service._get_provider_config_map",
            return_value={},
        ):
            result = _get_provider_config(provider)
            assert result.name == "unknown-provider"
            assert result.enabled is True
            assert result.priority == 50


class TestClearFallbackState:
    """Tests for _clear_fallback_state helper."""

    @pytest.mark.asyncio
    async def test_deletes_fallback_key(self) -> None:
        """Deletes the fallback state key from Redis."""
        mock_cache = MagicMock()
        mock_cache.delete = AsyncMock()

        with patch(
            "job_ingest_discovery_service.services.discovery_service._get_cache",
            return_value=mock_cache,
        ):
            await _clear_fallback_state("jobspy", JobBoardSource.INDEED)
            mock_cache.delete.assert_called_once()
            key_arg = mock_cache.delete.call_args[0][0]
            assert "provider_fallback" in key_arg
            assert "jobspy" in key_arg


class TestRecordError:
    """Tests for _record_error helper."""

    @pytest.mark.asyncio
    async def test_records_first_error(self) -> None:
        """First error creates new state with count=1."""
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._get_cache",
                return_value=mock_cache,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_settings",
                return_value=MagicMock(caching=MagicMock(ttls=MagicMock(fallback_state=3600))),
            ),
        ):
            consecutive, duration = await _record_error("jobspy", JobBoardSource.INDEED)
            assert consecutive == 1
            assert duration >= 0.0
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_increments_existing_error_state(self) -> None:
        """Subsequent errors increment consecutive count and track duration."""
        import time

        first_error_time = time.time() - 120.0
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value={"first_error_at": first_error_time, "consecutive_errors": 2})
        mock_cache.set = AsyncMock()

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._get_cache",
                return_value=mock_cache,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service.get_settings",
                return_value=MagicMock(caching=MagicMock(ttls=MagicMock(fallback_state=3600))),
            ),
        ):
            consecutive, duration = await _record_error("jobspy", JobBoardSource.INDEED)
            assert consecutive == 3
            assert duration >= 120.0


class TestShouldFallbackConsecutiveErrors:
    """Tests for _should_fallback with consecutive error logic."""

    @pytest.mark.asyncio
    async def test_returns_true_when_thresholds_met(self) -> None:
        """Returns True when consecutive errors and duration exceed thresholds."""
        config = MagicMock()
        config.fallback.enabled = True
        config.fallback.min_consecutive_errors = 3
        config.fallback.error_duration_threshold_seconds = 60
        config.fallback.rate_limit_wait_threshold_seconds = 30

        result_obj = MagicMock()
        result_obj.error_code = "connection_timeout"
        result_obj.retry_after_seconds = None

        with patch(
            "job_ingest_discovery_service.services.discovery_service._record_error",
            new_callable=AsyncMock,
            return_value=(5, 120.0),
        ):
            result = await _should_fallback("provider", JobBoardSource.INDEED, result_obj, config)
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_below_consecutive_threshold(self) -> None:
        """Returns False when consecutive errors below threshold."""
        config = MagicMock()
        config.fallback.enabled = True
        config.fallback.min_consecutive_errors = 5
        config.fallback.error_duration_threshold_seconds = 60
        config.fallback.rate_limit_wait_threshold_seconds = 30

        result_obj = MagicMock()
        result_obj.error_code = "connection_timeout"
        result_obj.retry_after_seconds = None

        with patch(
            "job_ingest_discovery_service.services.discovery_service._record_error",
            new_callable=AsyncMock,
            return_value=(2, 120.0),
        ):
            result = await _should_fallback("provider", JobBoardSource.INDEED, result_obj, config)
            assert result is False


class TestDiscoverFromSourceAllFail:
    """Tests for _discover_from_source when all providers fail."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_providers_return_none(self) -> None:
        """Returns empty list when all providers fail with fallback."""
        provider1 = MagicMock()
        provider1.name = "p1"
        provider2 = MagicMock()
        provider2.name = "p2"

        registry = MagicMock()
        registry.get_providers_for_source.return_value = [provider1, provider2]

        request = DiscoveryRequest(
            query_id="q-1",
            keywords=("python",),
            sources=(JobBoardSource.INDEED,),
            locations=(),
            work_arrangements=(),
            results_per_source=50,
        )

        with patch(
            "job_ingest_discovery_service.services.discovery_service._try_provider",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _discover_from_source(registry, request, JobBoardSource.INDEED)
            assert result == []


class TestRunDiscovery:
    """Tests for run_discovery orchestrator."""

    @pytest.mark.asyncio
    async def test_logs_warning_when_no_listings(self) -> None:
        """Logs warning and returns early when no listings found."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[JobBoardSource.INDEED],
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._build_discovery_request",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._discover_from_all_sources",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("job_ingest_discovery_service.services.discovery_service.logger") as mock_logger,
        ):
            await run_discovery(query, "d-1")
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovers_and_publishes(self) -> None:
        """Discovers listings and publishes them."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[JobBoardSource.INDEED],
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._build_discovery_request",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._discover_from_all_sources",
                new_callable=AsyncMock,
                return_value=[MagicMock()],
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._dedupe_and_publish",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_dedupe,
        ):
            await run_discovery(query, "d-1")
            mock_dedupe.assert_called_once()

    @pytest.mark.asyncio
    async def test_reraises_exceptions(self) -> None:
        """Re-raises exceptions after logging."""
        query = IngestionQuery(
            query_id="q-1",
            search_keywords=["python"],
            sources=[JobBoardSource.INDEED],
        )

        with (
            patch(
                "job_ingest_discovery_service.services.discovery_service._build_discovery_request",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await run_discovery(query, "d-1")
