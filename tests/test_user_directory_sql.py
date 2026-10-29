"""The PostgreSQL search expression must match the deployable indexes."""

from sqlalchemy.dialects import postgresql

from fintrack_core.user_directory import search_predicate


def test_postgres_search_uses_lower_expression_and_escapes_wildcards():
    for query in ("bo", "b%b_/"):
        statement = search_predicate(query).compile(dialect=postgresql.dialect())
        sql = str(statement)
        assert 'lower(neon_auth."user".name) LIKE' in sql
        assert 'lower(neon_auth."user".email) LIKE' in sql
        assert " ILIKE " not in sql
        assert "ESCAPE '/'" in sql
    params = search_predicate("b%b_/").compile(dialect=postgresql.dialect()).params
    assert "b/%b/_//" in params.values()


def test_complete_email_uses_indexable_equality():
    sql = str(search_predicate("BOB@example.test").compile(dialect=postgresql.dialect()))
    assert 'lower(neon_auth."user".email) = lower(' in sql
    assert "LIKE" not in sql
