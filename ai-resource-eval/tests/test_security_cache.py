"""Tests for the security_scan cache namespace isolation in EvalCache.make_key."""

from __future__ import annotations

import hashlib

from ai_resource_eval.cache.sqlite_cache import EvalCache


class TestNamespaceIsolation:
    """make_key with namespace produces keys that don't collide with the unnamespaced path."""

    def test_no_namespace_unchanged(self):
        """Calling make_key without namespace preserves the legacy byte-for-byte hash."""
        expected = hashlib.sha256(b"m:c:v").hexdigest()
        assert EvalCache.make_key("m", "c", "v") == expected
        assert EvalCache.make_key("m", "c", "v", namespace=None) == expected

    def test_security_namespace_differs(self):
        without = EvalCache.make_key("m", "c", "v")
        with_ns = EvalCache.make_key("m", "c", "v", namespace="security")
        assert without != with_ns

    def test_security_namespace_format(self):
        expected = hashlib.sha256(b"security|m:c:v").hexdigest()
        assert EvalCache.make_key("m", "c", "v", namespace="security") == expected

    def test_different_namespaces_yield_different_keys(self):
        sec = EvalCache.make_key("m", "c", "v", namespace="security")
        other = EvalCache.make_key("m", "c", "v", namespace="quality")
        assert sec != other

    def test_namespace_with_config_hash(self):
        expected = hashlib.sha256(b"security|m:c:v:cfg").hexdigest()
        assert (
            EvalCache.make_key("m", "c", "v", config_hash="cfg", namespace="security")
            == expected
        )


class TestRubricVersionInvalidation:
    """Bumping rubric_version invalidates security cache but not quality cache (and vice versa)."""

    def test_security_rubric_bump_invalidates_only_security(self):
        # Same content, same metric, different rubric_version inside security namespace
        sec_v1 = EvalCache.make_key("m", "c", "1.aaa", namespace="security")
        sec_v2 = EvalCache.make_key("m", "c", "2.bbb", namespace="security")
        assert sec_v1 != sec_v2

        # Quality (no namespace) cache key for the same entry is unaffected
        quality_v1 = EvalCache.make_key("m", "c", "1.aaa")
        # Either security key collides with the quality key
        assert quality_v1 != sec_v1
        assert quality_v1 != sec_v2

    def test_quality_rubric_bump_does_not_invalidate_security(self):
        quality_v1 = EvalCache.make_key("m", "c", "1.aaa")
        quality_v2 = EvalCache.make_key("m", "c", "2.bbb")
        # Security cache lives under the namespace; quality changes don't touch it
        security = EvalCache.make_key("m", "c", "1.aaa", namespace="security")
        assert security != quality_v1
        assert security != quality_v2

    def test_namespace_isolation_via_cache_get(self, tmp_path):
        """End-to-end via the SQLite cache: same metric/hash/rubric in two
        namespaces produces two independent rows that never collide on get()."""
        from datetime import datetime, timedelta, timezone

        from ai_resource_eval.cache.sqlite_cache import CacheEntry

        cache = EvalCache(db_path=tmp_path / "iso.db")
        try:
            now = datetime.now(timezone.utc)
            evaluated_at = now.isoformat()
            expires_at = (now + timedelta(days=1)).isoformat()

            quality_key = EvalCache.make_key("__full__", "ch1", "1.q")
            security_key = EvalCache.make_key(
                "__full__", "ch1", "1.q", namespace="security"
            )

            cache.put(
                quality_key,
                CacheEntry(
                    cache_key=quality_key,
                    entry_id="e1",
                    content_hash="ch1",
                    rubric_version="1.q",
                    result_json='{"kind":"quality"}',
                    evaluated_at=evaluated_at,
                    expires_at=expires_at,
                ),
            )
            cache.put(
                security_key,
                CacheEntry(
                    cache_key=security_key,
                    entry_id="e1",
                    content_hash="ch1",
                    rubric_version="1.q",
                    result_json='{"kind":"security"}',
                    evaluated_at=evaluated_at,
                    expires_at=expires_at,
                ),
            )

            got_q = cache.get(quality_key)
            got_s = cache.get(security_key)
            assert got_q is not None and got_s is not None
            assert got_q.result_json == '{"kind":"quality"}'
            assert got_s.result_json == '{"kind":"security"}'
        finally:
            cache.close()
