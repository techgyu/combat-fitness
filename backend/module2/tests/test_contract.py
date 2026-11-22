import pytest

from module2.catalog import load_catalog
from module2.contract import ContractError, validate_contract

from .fixtures import payload

CATALOG = load_catalog()


def test_catalog_has_30_consistent_exercises():
    assert len(CATALOG.exercises) == 30
    assert CATALOG.versions["exercise_catalog"] == "1.0"


def test_spec_example_is_accepted_and_needs_are_derived():
    pi = validate_contract(payload(), CATALOG)
    needs = {n.column: n for n in pi.needs}
    assert needs["pushups_2min"].direction == "increase" and needs["pushups_2min"].amount == 16
    assert needs["situps_2min"].direction == "increase" and needs["situps_2min"].amount == 18
    assert needs["run_3km_seconds"].direction == "decrease" and needs["run_3km_seconds"].amount == 148
    assert pi.improvement_columns == ["pushups_2min", "situps_2min", "run_3km_seconds"]


def test_met_column_is_marked_met():
    p = payload(difference_matrix=[[0, 18, -148, 0]],
                current_records={"pushups_2min": 64, "situps_2min": 60, "run_3km_seconds": 960})
    pi = validate_contract(p, CATALOG)
    assert pi.improvement_columns == ["situps_2min", "run_3km_seconds"]


@pytest.mark.parametrize("override, fragment", [
    ({"column_order": ["situps_2min", "pushups_2min", "run_3km_seconds", "load_to_body_weight_ratio"]}, "column_order"),
    ({"column_units": ["reps", "reps", "minutes", "ratio"]}, "column_units"),
    ({"schema_version": "1.0"}, "schema_version"),
    ({"difference_matrix": [[16, 18, -148]]}, "shape"),
    ({"difference_matrix": [[16, 18, 148, 0]]}, "goal - current"),
    ({"difference_matrix": [[-2, 18, -148, 0]]}, "goal - current"),
    ({"difference_matrix": [[16, 18, -148, 0.1]]}, "load_to_body_weight_ratio: must be 0"),
    ({"difference_matrix": [[15, 18, -148, 0]]}, "goal - current"),
    ({"load_context": {"combat_load_kg": 20, "load_to_body_weight_ratio": 0.2667, "usage": "reference_only"}},
     "combat_load_kg"),
    ({"load_context": {"combat_load_kg": 15, "load_to_body_weight_ratio": 0.3, "usage": "reference_only"}},
     "combat_load_kg / weight_kg"),
    ({"load_context": {"combat_load_kg": 15, "load_to_body_weight_ratio": 0.2, "usage": "weight"}}, "usage"),
    ({"versions": {"exercise_catalog": "0.9"}}, "versions.exercise_catalog"),
])
def test_contract_violations_are_rejected(override, fragment):
    with pytest.raises(ContractError) as e:
        validate_contract(payload(**override), CATALOG)
    assert any(fragment in issue for issue in e.value.issues), e.value.issues


def test_missing_field_and_wrong_type_are_rejected():
    p = payload()
    del p["current_records"]
    with pytest.raises(ContractError):
        validate_contract(p, CATALOG)
    with pytest.raises(ContractError):
        validate_contract(payload(difference_matrix=[["a", 18, -148, 0]]), CATALOG)


def test_non_synthetic_soldier_is_rejected():
    p = payload()
    p["soldier"]["synthetic"] = False
    with pytest.raises(ContractError):
        validate_contract(p, CATALOG)
