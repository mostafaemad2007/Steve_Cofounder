"""A small JSON Schema subset, used to check what the model returns.

Supports type, required, properties, items, enum, minItems, maxItems, minimum, maximum, minLength.
That is enough to reject a malformed agent reply without adding a dependency, and the same schema
is passed to Ollama as its `format`, so the model is constrained on the way out as well as checked
on the way in.
"""
TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


class SchemaError(ValueError):
    """Raised when data does not match the schema."""


def validate(value, schema: dict, path: str = "$") -> None:
    expected = schema.get("type")
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, name) for name in names):
            raise SchemaError(f"{path}: expected {expected}, got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise SchemaError(f"{path}: text is too short (needs {schema['minLength']} characters)")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaError(f"{path}: {value} is above the maximum {schema['maximum']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}: missing '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, f"{path}.{key}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaError(f"{path}: needs at least {schema['minItems']} items, got {len(value)}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaError(f"{path}: at most {schema['maxItems']} items, got {len(value)}")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{index}]")


def _is_type(value, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False          # a boolean is not a number here, whatever Python says
    return isinstance(value, TYPES[name])


# -- shorthands for building agent schemas ------------------------------------
def s(min_length: int = 1) -> dict:
    return {"type": "string", "minLength": min_length}


def arr(items: dict, min_items: int = 0, max_items: int | None = None) -> dict:
    schema = {"type": "array", "items": items, "minItems": min_items}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def obj(properties: dict, title: str | None = None) -> dict:
    schema = {"type": "object", "properties": properties, "required": list(properties)}
    if title:
        schema["title"] = title
    return schema


#: Every agent claim: free text, an optional source id from the excerpts, and a confidence level.
CLAIMS = arr(obj({
    "text": s(5),
    "source_id": {"type": ["string", "null"]},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
}))
