import psycopg
import pytest

from steuer_chatbot.settings import get_commute_distance, set_commute_distance


def test_commute_distance_is_unset_initially(conn: psycopg.Connection) -> None:
    assert get_commute_distance(conn) is None


def test_commute_distance_can_be_set(conn: psycopg.Connection) -> None:
    set_commute_distance(conn, 42.0)

    assert get_commute_distance(conn) == 42.0


def test_setting_the_commute_distance_again_overwrites_it(conn: psycopg.Connection) -> None:
    set_commute_distance(conn, 42.0)
    set_commute_distance(conn, 37.5)

    assert get_commute_distance(conn) == 37.5
    assert conn.execute("SELECT count(*) FROM settings").fetchone() == (1,)


@pytest.mark.parametrize("km", [0.0, -5.0, float("nan"), float("inf")])
def test_invalid_commute_distance_is_rejected(conn: psycopg.Connection, km: float) -> None:
    with pytest.raises(ValueError):
        set_commute_distance(conn, km)

    assert get_commute_distance(conn) is None
