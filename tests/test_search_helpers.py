from backend.h5_backend.services.shared.search import contains_like_pattern


def test_contains_like_pattern_escapes_wildcards():
    assert contains_like_pattern("%") == "%\\%%"
    assert contains_like_pattern("_") == "%\\_%"
    assert contains_like_pattern("plan_100%") == "%plan\\_100\\%%"
