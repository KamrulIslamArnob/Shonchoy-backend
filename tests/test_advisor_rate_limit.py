from fintrack_core.advisor_rate_limit import AdvisorRateLimiter


def test_rate_limit_is_per_user_and_expires() -> None:
    now = [100.0]
    limiter = AdvisorRateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert limiter.allow("alice")
    assert limiter.allow("alice")
    assert not limiter.allow("alice")
    assert limiter.allow("bob")
    assert all(b"alice" not in key for key in limiter.entries)
    now[0] += 61
    assert limiter.allow("alice")
