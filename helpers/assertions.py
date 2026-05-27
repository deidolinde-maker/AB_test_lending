def assert_expected_vs_actual(step: str, expected: object, actual: object) -> None:
    assert expected == actual, f"Step: {step}\nExpected: {expected}\nActual: {actual}"


def assert_not_found(step: str, actual_values: list[str], unexpected: str) -> None:
    normalized = [value.lower() for value in actual_values]
    assert unexpected.lower() not in normalized, (
        f"Step: {step}\nExpected not found: {unexpected}\nActual suggest list: {actual_values}"
    )

