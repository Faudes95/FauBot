import os

os.environ.setdefault("PROSTANET_MHSPC_REFERENCE_ROOT", "/tmp/faubot_mhspc_reference_tests")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from prostanet.domains.evidence_registry.pivotal_catalog import (  # noqa: E402
    PIVOTAL_STUDY_CATALOG,
    REQUESTED_PIVOTAL_STUDY_NAMES,
    build_flagship_patient_suite,
    get_pivotal_profile,
    normalize_study_name,
)
from pivotal_studies import get_study_details, match_patient_to_studies, run_flagship_patient_suite  # noqa: E402


def _target_match(study_name, payload):
    key = normalize_study_name(study_name)
    for item in match_patient_to_studies(payload):
        if normalize_study_name((item.get("study") or {}).get("name")) == key:
            return item
    raise AssertionError(f"No match returned for {study_name}")


def test_requested_pivotal_catalog_is_complete_and_aliasable():
    assert len(REQUESTED_PIVOTAL_STUDY_NAMES) == 36
    assert len(PIVOTAL_STUDY_CATALOG) == 36

    catalog_names = {item["canonical_name"] for item in PIVOTAL_STUDY_CATALOG}
    assert set(REQUESTED_PIVOTAL_STUDY_NAMES) == catalog_names

    for profile in PIVOTAL_STUDY_CATALOG:
        assert profile["source_citations"], profile["canonical_name"]
        assert profile["required_inputs"], profile["canonical_name"]
        assert profile["adverse_event_watchlist"], profile["canonical_name"]
        assert profile["contraindication_flags"], profile["canonical_name"]
        assert profile["flagship_patient"]["payload"], profile["canonical_name"]
        assert get_study_details(profile["canonical_name"])["name"] == profile["canonical_name"]
        for alias in profile.get("aliases", []):
            assert get_pivotal_profile(alias)["canonical_name"] == profile["canonical_name"]
            assert get_study_details(alias)["name"] == profile["canonical_name"]


def test_flagship_patient_suite_matches_all_requested_studies():
    suite = run_flagship_patient_suite()

    assert len(suite) == 36
    assert all(item["eligible"] for item in suite)
    assert all(item["adverse_event_watchlist"] for item in suite)
    assert all(item["expected"].get("module_id") for item in suite)
    assert {item["study_name"] for item in suite} == set(REQUESTED_PIVOTAL_STUDY_NAMES)


def test_pivotal_matching_exposes_safety_gap_fields_for_contraindications():
    cases = {case["study_name"]: case for case in build_flagship_patient_suite()}

    chaarted_payload = dict(cases["CHAARTED"]["payload"])
    chaarted_payload.update({"peripheral_neuropathy_grade": 3})
    chaarted = _target_match("CHAARTED", chaarted_payload)
    assert chaarted["eligible"] is False
    assert any(flag["severity"] == "hard_stop" for flag in chaarted["contraindication_flags"])
    assert any("Neuropatia" in flag["label"] for flag in chaarted["contraindication_flags"])
    assert chaarted["adverse_event_watchlist"]
    assert chaarted["clinical_gap_reason"]

    vision_payload = dict(cases["VISION"]["payload"])
    vision_payload.update({"psma_pet_result": "Negativo", "psma_negative_dominant_lesions": True})
    vision = _target_match("VISION", vision_payload)
    assert vision["eligible"] is False
    assert any(flag["severity"] == "hard_stop" for flag in vision["contraindication_flags"])
    assert vision["missing_required_inputs"] == []


def test_core_aliases_resolve_without_losing_canonical_trial_identity():
    expected = {
        "PRESTO": "PRESTO / AFT-19",
        "AFT-19": "PRESTO / AFT-19",
        "TAX 327": "TAX-327",
        "PSMAFORE": "PSMAfore",
        "THERAP": "TheraP",
        "PROPEL": "PROpel",
        "IPATENTIAL150": "IPATential150",
        "CONTACT 02": "CONTACT-02",
    }
    for alias, canonical in expected.items():
        assert get_study_details(alias)["name"] == canonical
