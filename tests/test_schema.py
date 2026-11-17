"""Part 5a: the JSON Schema subset used to check model replies."""
import pytest

from venturegate.schema import CLAIMS, SchemaError, arr, obj, s, validate


def test_accepts_a_well_formed_object():
    schema = obj({"name": s(), "score": {"type": "integer", "minimum": 1, "maximum": 5}})
    validate({"name": "Founder idea", "score": 4}, schema)


@pytest.mark.parametrize("value, why", [
    ({"score": 4}, "missing 'name'"),
    ({"name": "", "score": 4}, "empty name"),
    ({"name": "x", "score": 9}, "above maximum"),
    ({"name": "x", "score": 0}, "below minimum"),
    ({"name": "x", "score": "4"}, "wrong type"),
    ({"name": "x", "score": True}, "a boolean is not an integer"),
])
def test_rejects_bad_objects(value, why):
    schema = obj({"name": s(), "score": {"type": "integer", "minimum": 1, "maximum": 5}})
    with pytest.raises(SchemaError):
        validate(value, schema)


def test_array_bounds_are_enforced():
    schema = arr(s(), 3, 5)
    validate(["a", "b", "c"], schema)
    with pytest.raises(SchemaError, match="at least 3"):
        validate(["a"], schema)
    with pytest.raises(SchemaError, match="at most 5"):
        validate(list("abcdef"), schema)


def test_enum_and_nullable_types():
    schema = obj({"status": {"type": "string", "enum": ["clear", "risk", "unknown"]},
                  "source_id": {"type": ["string", "null"]}})
    validate({"status": "risk", "source_id": None}, schema)
    validate({"status": "clear", "source_id": "S2"}, schema)
    with pytest.raises(SchemaError, match="not one of"):
        validate({"status": "maybe", "source_id": None}, schema)


def test_errors_name_the_path_so_a_retry_can_fix_it():
    schema = obj({"options": arr(obj({"name": s()}), 1)})
    with pytest.raises(SchemaError, match=r"\$\.options\[0\]"):
        validate({"options": [{"name": 5}]}, schema)


def test_claims_shape():
    validate([{"text": "A sourced claim", "source_id": "S1", "confidence": "high"},
              {"text": "An assumption", "source_id": None, "confidence": "low"}], CLAIMS)
    with pytest.raises(SchemaError):
        validate([{"text": "x", "source_id": "S1", "confidence": "certain"}], CLAIMS)
