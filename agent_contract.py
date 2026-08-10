"""Shared bounded-workflow configuration."""

MAX_AGENT_RETRIES = 3


def validate_max_retries(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("max_retries must be an integer from 0 to 3")
    if value < 0 or value > MAX_AGENT_RETRIES:
        raise ValueError("max_retries must be from 0 to 3")
    return value
