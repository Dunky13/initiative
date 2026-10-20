"""The worker answers each request within its bounds, parsing an expression
once and deciding a predicate without leaving the process."""

import time

from app.services import jsonata_worker

BOUNDS = (1000, 100, 65536)


def test_an_expression_is_parsed_once():
    """Parsed on its first run, and run again with a fresh time bound: one
    parsed longer ago than the bound still answers."""
    jsonata_worker._parsed.cache_clear()
    brief = (20, 100, 65536)

    assert jsonata_worker.answer({"expression": "1 + 1"}, brief) == {"value": 2}
    time.sleep(0.05)
    assert jsonata_worker.answer({"expression": "1 + 1", "document": 5}, brief) == {
        "value": 2
    }
    assert jsonata_worker._parsed.cache_info().hits == 1


def test_a_predicate_answers_what_boolean_says():
    answers = [
        jsonata_worker.answer({"expression": text, "predicate": True}, BOUNDS)
        for text in ("[]", '"x"', "0", '{"a": 1}', "$nothing")
    ]

    assert answers == [
        {"value": False},
        {"value": True},
        {"value": False},
        {"value": True},
        {"undefined": True},
    ]
