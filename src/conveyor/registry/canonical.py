"""The canonical JSON form that agent version identity is computed from.

Values are serialised with the JSON Canonicalization Scheme (RFC 8785, see ADR 0013): object
keys sorted by their UTF-16 code units, no insignificant whitespace, UTF-8 output and numbers
written the way ECMAScript prints them. Two values with the same meaning therefore always
serialise to the same bytes, whatever their key order or how their numbers were written, and
those bytes can be hashed.
"""

import json

import rfc8785
from pydantic import JsonValue

MAX_SAFE_INTEGER = 2**53 - 1
"""Largest integer JSON can carry exactly; RFC 8785 rejects anything beyond it."""


class CanonicalFormError(ValueError):
    """Raised when a value has no canonical form, or bytes are not in canonical form."""


def canonical_json(value: JsonValue) -> bytes:
    """Serialise a JSON value in canonical form.

    Args:
        value: The value to serialise.

    Returns:
        The RFC 8785 serialisation, as UTF-8 bytes.

    Raises:
        CanonicalFormError: If the value contains something JSON cannot represent exactly:
            NaN or an infinity, an integer beyond +/-(2**53 - 1), or a lone surrogate.
    """
    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as error:
        message = f"value has no canonical JSON form: {error}"
        raise CanonicalFormError(message) from error


def _parse_int(text: str) -> int | float:
    # Canonical output never holds an integer beyond the safe range unless it came from a
    # whole-valued float such as 1e20, which RFC 8785 prints without an exponent. Read it back
    # as the float it was, so that it serialises to the same bytes again.
    number = int(text)
    return float(number) if abs(number) > MAX_SAFE_INTEGER else number


def load_canonical_json(data: bytes) -> JsonValue:
    """Parse bytes that must already be in canonical form.

    Args:
        data: Bytes produced by `canonical_json`.

    Returns:
        The parsed value. Serialising it again gives back `data` exactly.

    Raises:
        CanonicalFormError: If `data` is not JSON, or is JSON but not in canonical form (extra
            whitespace, unsorted or duplicate keys, a number written differently, ...).
    """
    try:
        value: JsonValue = json.loads(data, parse_int=_parse_int)
    except ValueError as error:
        message = f"not valid UTF-8 JSON: {error}"
        raise CanonicalFormError(message) from error
    if canonical_json(value) != data:
        message = "JSON is not in canonical form (RFC 8785)"
        raise CanonicalFormError(message)
    return value
