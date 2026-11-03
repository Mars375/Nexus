"""Chemins et noms à barres obliques que le scanner de secrets laisse intacts (#87, ADR-006)."""

import pytest

from nexus.secrets import REDACTED, redact


@pytest.mark.parametrize(
    "text",
    [
        "serveur/src/nexus/secrets.py",
        "/var/backups/2026-10-18/nexus.db",
        "https://example.org/documentation_officielle_2026/notes/finales",
        "https://example.org/une_variable_tres_longue_2026/archives/notes_finales",
        "deployments/v1_release_20261018/build_artifacts_run42/output.log",
        "https://cdn.example.org/v1_release_20261018/build_artifacts_run42/output",
        "deployments/20261018/releases/build42/output",
    ],
)
def test_paths_with_slashes_stay_untouched(text):
    # The slashed-pattern guard (#84): a path of words is not an opaque value,
    # even when it is long and carries digits (Antigravity review on 6d78a6c:
    # deployment/build paths used to pass the guard and were erased).
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "Deployments/V1Release2026Build/Build42Output2026",
        "Apps/V2Prod2026/Release42Build/Deploy20261018",
        "src/views/AccountSettingsV2/OAuth2Callback",
        "components/AuthDialogV2/Step1EmailAddress",
        "api/Version2/PaymentGateway3/ProcessOrder",
        "app/Http/Controllers/ApiV2/Auth3StepFlow",
    ],
)
def test_case_mixed_paths_and_names_stay_untouched(text):
    # Antigravity and reviewer reviews on c73aee9: the previous guard masked a
    # path part merely for mixing case and digits (`Deployments/V1Release…`,
    # `…AccountSettingsV2/OAuth2Callback`). A path names its parts: neither
    # signal of `_blob_segment` fires on a word or a version number.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "Dev/Ops/Tool/Run12345/Log6789",
        "Src/App/Doc/Test1/Build2",
        "App/Api/Doc/Web/Job1/Log2",
        "Pkg/Src/Doc/Lib1/Bin2026",
    ],
)
def test_short_titlecase_word_paths_stay_untouched(text):
    # Antigravity review on 5b186c5: a three-letter TitleCase word holds a
    # two-character lowercase run, below the words veto, and chains of them
    # were erased on their word-start capitals alone (a regression against
    # master, where they stayed intact). A change that only opens a word is
    # not a shuffle.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/org/repo/releases/v1rc1/v2rc2",
        "kubernetes/crds/v1a1/v1b1",
        "download/ubuntu/v1rc1/v2rc2",
        "terraform/modules/compute/g4dn/c5ad",
        "git checkout refs/heads/release/v1rc1/g4dn",
        "api/v1/users/getById/v2b1",
        "src/controllers/users/getById/v2rc1",
        "endpoints/tasks/toDoList/v1b1",
        "controllers/DevSecOps/getById2",
    ],
)
def test_release_tags_and_camel_case_routes_stay_untouched(text):
    # Antigravity review on d2361cc (F3): a four-to-five character version tag
    # (`v1rc1`, `g4dn`) alternates letters and digits at the scale of a name,
    # and a camelCase method shuffles case between its short words. The blob
    # floor (six pairs) and the words veto of the guard keep both families
    # intact.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/v1/controllers/DevSecOps/v1a1",
        "https://example.com/api/v1/controllers/DevSecOps/v1a1",
        "src/controllers/DevSecOps/v1a1",
        "controllers/DevSecOps/v1a1",
    ],
)
def test_route_with_a_mixed_case_name_and_a_version_tag_stays_untouched(text):
    # Antigravity review on 5efcee9: the rescue arm accepted a single
    # signal-shaped chunk (`any`) while the same shape reads as a phrase — a
    # word beside an alternating segment (`controllers` beside `v1a1`) no
    # longer lets its blob (the mixed-case name) mask the run. The bare route
    # was already masked on cc0eeb3 (the `any` arm of the whole guard); the
    # three prefixed forms were regressions against it.
    assert redact(text) == (text, [])


def test_hexadecimal_segment_in_an_asset_path_is_masked_as_assumed():
    # issue #84, fourth disposition: over-masking assumed (never a leak); the
    # honest fix needs a path-context heuristic — the current behaviour is
    # pinned here so the assumption stays visible.
    text = "https://example.org/assets/0123456789abcdef0123456789abcdef/logo.svg"
    cleaned, found = redact(text)
    assert cleaned == f"https://example.org/assets/{REDACTED}/logo.svg"
    assert found == ["high_entropy"]
