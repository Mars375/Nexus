"""Quotes and apostrophes inside a credential value (issue #106).

Every label and value is assembled at runtime: a credential-shaped literal in
this file would be rewritten to `[REDACTED]` by the pre-commit hook (or flagged
by gitleaks), which silently turns an assertion into a no-op.
"""

import random
import time

import pytest

from nexus.secrets import REDACTED, redact

PW = "pass" + "word"
MDP = "mot de " + "passe"
TK = "tok" + "en"
SEC = "sec" + "ret"
AK = "api" + "_key"
VALUE = "LesChats" + "2026"


def assert_masked(text: str, expected: str) -> None:
    """One credential is masked whole, and a second pass changes nothing."""
    cleaned, found = redact(text)

    assert cleaned == expected
    assert found == ["credential"]
    assert redact(cleaned) == (cleaned, [])


# 1. An apostrophe inside a bare value does not end it.
def test_apostrophe_inside_a_bare_value_is_masked_whole():
    assert_masked(MDP + " : j'aime" + VALUE + " tous", MDP + " : " + REDACTED)


# 2. The same with an accent after the apostrophe.
def test_accented_apostrophe_value_is_masked_whole():
    assert_masked(PW + ": l'étéZq7 brûlant", PW + ": " + REDACTED)


# 3. An escaped quote inside a double-quoted JSON value.
def test_escaped_double_quote_inside_a_json_value_is_masked_whole():
    text = '{"' + PW + '": "pa\\"ss' + "Zq7Wx" + '"}'

    assert_masked(text, '{"' + PW + '": "' + REDACTED + '"}')


# 4. An escaped apostrophe inside a single-quoted value.
def test_escaped_single_quote_inside_a_quoted_value_is_masked_whole():
    text = "{'" + TK + "': 'it\\'s" + "Zq7'}"

    assert_masked(text, "{'" + TK + "': '" + REDACTED + "'}")


# 5. A doubled backslash before the closing quote (already green on master).
def test_doubled_backslash_before_the_closing_quote_is_masked_whole():
    text = '{"' + SEC + '": "Zq7' + "\\\\" + '", "note": "ok"}'

    assert_masked(text, '{"' + SEC + '": "' + REDACTED + '", "note": "ok"}')


# 6. JSON nested inside JSON: the inner value stays escaped.
def test_json_inside_json_is_masked_whole():
    text = '{"body": "{\\"' + PW + '\\": \\"' + "hun" + "ter2Zq" + '\\"}"}'

    # The backslash that escapes the closing quote stays with it (amendment 2).
    assert_masked(text, '{"body": "{\\"' + PW + '\\": ' + REDACTED + '\\"}"}')


# 7. A quoted value that is never closed stops at the end of its line.
@pytest.mark.parametrize("quote", ['"', "'"])
def test_unterminated_quoted_value_is_closed_at_end_of_line(quote):
    text = "DB_" + PW.upper() + "=" + quote + "hun" + "Zq7Wx"

    assert_masked(text, "DB_" + PW.upper() + "=" + quote + REDACTED + quote)


# 8. A multi-word value between quotes, never closed, is masked whole.
def test_multi_word_unterminated_quoted_value_is_masked_whole():
    assert_masked(AK + ': "abc def ' + "Zq7 ghi", AK + ': "' + REDACTED + '"')


# 9. A value that opens a quote on its line, followed by another assignment.
def test_unterminated_value_does_not_swallow_the_next_assignment():
    text = "DB_" + PW.upper() + '="abc' + "Zq7" + "\n" + AK.upper() + '="' + "Zq9" + "def" + '"'

    assert_masked(
        text,
        "DB_" + PW.upper() + '="' + REDACTED + '"\n' + AK.upper() + '="' + REDACTED + '"',
    )


# 10. A well-closed value spanning two lines stays masked whole (non-regression).
def test_well_closed_quoted_value_spanning_two_lines_is_masked_whole():
    text = PW + ': "Zq7 multi\nligneZq8"'

    assert_masked(text, PW + ': "' + REDACTED + '"')


# 11. Shell-style escaped apostrophe glued after the closing quote.
def test_shell_escaped_apostrophe_value_is_masked_whole():
    text = "export DB_" + PW.upper() + "='j'\\''aime" + "Zq7'"

    assert_masked(text, "export DB_" + PW.upper() + "='" + REDACTED + "'")


# 12. Plain apostrophe glued after the closing quote.
def test_apostrophe_glued_after_the_closing_quote_is_masked_whole():
    text = MDP + " : 'j'aime les chats" + "Zq7'"

    assert_masked(text, MDP + " : '" + REDACTED + "'")


# 13. Quotes inside a value, quoted or bare, in each combination.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PW + '="pa"ss' + "Zq7", PW + '="' + REDACTED + '"'),
        (PW + ": 'it''s" + "Zq7'", PW + ": '" + REDACTED + "'"),
        (TK + ": ''" + "Zq7glued", TK + ": '" + REDACTED + "'"),
        (PW + '="Zq7"x\'', PW + '="' + REDACTED + '"'),
    ],
)
def test_quotes_inside_a_value_are_masked_whole(text, expected):
    assert_masked(text, expected)


# 14. Prose around a quoted value keeps its closing quote and the rest of the line.
def test_closing_quote_and_the_prose_after_it_stay_in_place():
    text = 'Il a dit "' + PW + ': voir Bitwarden" dans le canal.'

    assert_masked(text, 'Il a dit "' + PW + ': ' + REDACTED + '" dans le canal.')


# 15. Prose without a separator is left untouched.
@pytest.mark.parametrize(
    "text",
    [
        "Le " + MDP + " d'Alice expire demain.",
        "Ton " + MDP + " n'est pas assez long.",
        "L'option --" + PW + " n'est plus acceptée.",
        'Voir "' + MDP + '" dans le glossaire.',
    ],
)
def test_prose_without_a_separator_is_untouched(text):
    assert redact(text) == (text, [])


# 16. The mask is idempotent on random combinations of hostile pieces.
def test_masking_is_idempotent_on_random_input():
    pieces = [
        PW + "=",
        MDP + " : ",
        '"',
        "'",
        "\\",
        " ",
        "\n",
        "\r\n",
        "j'aime",
        "[",
        "]",
        ",",
        ";",
        "}",
        REDACTED,
        "é",
        "`",
        ")",
    ]
    rng = random.Random(106)
    for _ in range(2000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        cleaned, _found = redact(text)
        assert redact(cleaned) == (cleaned, [])


# 17. Hostile 100 KB inputs stay linear. Short ids: pytest exports the node id
# in `PYTEST_CURRENT_TEST`, which Windows caps at 32767 characters.
@pytest.mark.parametrize(
    "text",
    [
        PW + '="' + '\\"' * (100_000 // 2),
        PW + '="' + "\\" * 100_000,
        PW + ": " + "a'" * (100_000 // 2),
        PW + '="' + "\n" * 100_000,
        PW + '="' + ("\n" + PW) * (100_000 // (len(PW) + 1)),
        (PW + '="a ') * (100_000 // (len(PW) + 4)),
        MDP + " : " + ("j'aime " * (100_000 // 7)),
    ],
    ids=[
        "escaped_quotes",
        "backslashes",
        "apostrophes",
        "newlines",
        "labels_per_line",
        "repeated_assignment",
        "passphrase_words",
    ],
)
def test_hostile_100k_inputs_stay_linear(text):
    started = time.perf_counter()
    redact(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0


# Amendment (review of PR #116): a value that runs across quotes must never swallow
# another label that master's scan, stopped at the quote, reached and masked.
WORD = "Les" + "Chats"
MARK_A = "Zq7" + "a"
MARK_B = "Zq7" + "b"


# 18. A quoted label after a passphrase keeps its own value masked whole.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            PW + ": " + WORD + ' "' + AK + '": "' + MARK_A + "," + MARK_B + '"',
            PW + ": " + REDACTED + ' "' + AK + '": "' + REDACTED + '"',
        ),
        (
            PW + ": " + WORD + " '" + TK + "': '" + MARK_A + ", " + MARK_B + "'",
            PW + ": " + REDACTED + " '" + TK + "': '" + REDACTED + "'",
        ),
        (
            PW + ': "x"y "' + TK + '": "' + MARK_A + "," + MARK_B + '"',
            PW + ': "' + REDACTED + '" "' + TK + '": "' + REDACTED + '"',
        ),
        (
            PW + ": " + WORD + '"' + TK + '": "' + MARK_A + "," + MARK_B + '"',
            PW + ": " + REDACTED + '"' + TK + '": "' + REDACTED + '"',
        ),
    ],
    ids=["double_quoted", "single_quoted", "after_glued_word", "glued_to_the_word"],
)
def test_quoted_label_after_a_value_keeps_its_value_masked(text, expected):
    assert_masked(text, expected)


# 19. The same label with its value on the next line.
def test_quoted_label_with_its_value_on_the_next_line_is_masked():
    text = PW + ": " + WORD + ' "' + TK + '":\n  ' + MARK_A

    assert_masked(text, PW + ": " + REDACTED + ' "' + TK + '":\n  ' + REDACTED)


# 20. A quoted label glued after a bracket shell.
def test_quoted_label_glued_after_a_bracket_shell_is_masked():
    text = PW + "=" + REDACTED + '"' + TK + '": ' + MARK_A

    assert_masked(text, PW + "=" + REDACTED + '"' + TK + '": ' + REDACTED)


# 21. A label at the end of a line, inside a value: the next line is masked too.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PW + ": " + MARK_A + "#" + TK + ":\n  " + MARK_B, PW + ": " + REDACTED),
        (PW + ": " + TK + ":\n  " + MARK_B, PW + ": " + REDACTED),
        (PW + ": [x." + TK + ":\n  " + MARK_B, PW + ": " + REDACTED),
        (PW + ": '" + MARK_A + " " + TK + ":\n  " + MARK_B, PW + ": '" + REDACTED + "'"),
    ],
    ids=["glued", "value_start", "bracket", "unterminated_quote"],
)
def test_label_at_the_end_of_a_line_inside_a_value_masks_the_next_line(text, expected):
    assert_masked(text, expected)


# 22. A value that starts on a quoted label: that label's value is masked.
def test_value_that_starts_on_a_quoted_label_masks_that_labels_value():
    text = PW + ': "' + TK + '": ' + MARK_A

    assert_masked(text, PW + ': "' + TK + '": ' + REDACTED)


# 23. Markers, quotes and separators only: already masked, left alone.
def test_value_made_of_markers_and_quotes_is_left_alone():
    text = TK + "=" + REDACTED + "'" + REDACTED + ":"

    assert redact(text) == (text, [])


# 24. Hostile 100 KB inputs for the label checks stay linear.
@pytest.mark.parametrize(
    "text",
    [
        PW + ": a" + ("'" + TK + "':") * (100_000 // 8),
        PW + ": a" + (' "' + TK + '":') * (100_000 // 9),
        PW + ": " + ("a#" + TK + ":\n") * (100_000 // 9),
        PW + "='" + ("x " + TK + ":\n") * (100_000 // 9),
        PW + "=[" + (TK + ":\n") * (100_000 // 7),
        PW + ": x'" + "aB" * (100_000 // 2),
        PW + ': "a"' + ("b'" + TK + "'=") * (100_000 // 9),
    ],
    ids=[
        "quoted_labels_glued",
        "quoted_labels_words",
        "line_end_labels",
        "unterminated_line_end",
        "bracket_line_end",
        "camel_run",
        "glued_after_quote",
    ],
)
def test_hostile_100k_label_inputs_stay_linear(text):
    started = time.perf_counter()
    redact(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0


# Amendment 2 (second review of PR #116). MARK_C stays a marker, never a label.
MARK_C = "Zq7" + "c"
# Two `.env` entries left empty, then the third variable's name.
ENV_HEAD = PW.upper() + "=\n" + TK.upper() + "=\n" + AK.upper()


# 25. A label left empty at the end of its line, then a line that opens another
# assignment (YAML nesting, empty `.env` entries): that assignment keeps its label
# and its value is masked whole.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "auth:\n  " + PW + ":\n  " + TK + ":\n  " + AK + ': "' + MARK_A + "," + MARK_B + '"\n',
            "auth:\n  " + PW + ":\n  " + TK + ":\n  " + AK + ': "' + REDACTED + '"\n',
        ),
        (
            ENV_HEAD + '="' + MARK_A + "," + MARK_B + '"',
            ENV_HEAD + '="' + REDACTED + '"',
        ),
        (
            ENV_HEAD + "=[" + MARK_A + ", " + MARK_B + "]",
            ENV_HEAD + "=" + REDACTED,
        ),
        (
            PW + ": x#" + TK + ":\n" + AK + ': "' + MARK_A + "," + MARK_B + '"',
            PW + ": " + REDACTED + "\n" + AK + ': "' + REDACTED + '"',
        ),
    ],
    ids=["yaml_nested", "env_quoted", "env_list", "glued_label_at_line_end"],
)
def test_empty_label_before_another_assignment_keeps_that_value_masked(text, expected):
    assert_masked(text, expected)


# 26. A lone backslash before a separator is no separator: the next label is found.
def test_lone_backslash_before_a_separator_does_not_hide_the_next_label():
    text = TK + "\\:" + PW + '" =' + MARK_A

    assert_masked(text, TK + "\\:" + PW + '" =' + REDACTED)


# 27. A label with no value after it stays inside the value that reached it.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PW + ":[]" + MARK_A + "w_" + PW.upper() + ":", PW + ":" + REDACTED),
        (TK + ":w " + MARK_C + "-" + TK + '":', TK + ":" + REDACTED),
    ],
    ids=["after_a_bracket", "quote_before_the_separator"],
)
def test_label_without_a_value_stays_inside_the_value(text, expected):
    assert_masked(text, expected)


# 28. Idempotence on shapes found by the review: a second pass changes nothing.
@pytest.mark.parametrize(
    "text",
    [
        PW + ":'''q7fwinScret" + "client" + "Secret=",
        TK + ':"\n\'\'' + MDP + ':\\"',
        MDP + ':\\"' + MARK_C + "w" + WORD + "DB_" + PW.upper() + '":',
    ],
    ids=["glued_after_empty_quotes", "escaped_quote_at_line_end", "prefixed_quoted_label"],
)
def test_second_pass_changes_nothing(text):
    cleaned, _found = redact(text)

    assert redact(cleaned) == (cleaned, [])
