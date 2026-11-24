import pytest

from app.models.enums import BloodType as B
from app.services.matching_rules import compatible_donor_types, is_compatible

PAIRS = [(donor, recipient) for donor in B for recipient in B]

# The table from the Matching Algorithm document, section 4.
DOCUMENT_TABLE = {
    B.O_NEG: {B.O_NEG},
    B.O_POS: {B.O_NEG, B.O_POS},
    B.A_NEG: {B.O_NEG, B.A_NEG},
    B.A_POS: {B.O_NEG, B.O_POS, B.A_NEG, B.A_POS},
    B.B_NEG: {B.O_NEG, B.B_NEG},
    B.B_POS: {B.O_NEG, B.O_POS, B.B_NEG, B.B_POS},
    B.AB_NEG: {B.O_NEG, B.A_NEG, B.B_NEG, B.AB_NEG},
    B.AB_POS: set(B),
}


def antigens(blood_type: B) -> set[str]:
    """The markers on the red cells: A, B and the Rh factor."""
    name = blood_type.value
    found = {letter for letter in ("A", "B") if letter in name}
    if name.endswith("+"):
        found.add("Rh")
    return found


@pytest.mark.parametrize(
    "donor,recipient",
    PAIRS,
    ids=[f"{donor.value} to {recipient.value}" for donor, recipient in PAIRS],
)
def test_compatibility_follows_the_antigen_rule(donor, recipient):
    # A donor can give when the recipient already has every marker the donor's cells carry.
    assert is_compatible(donor, recipient) is (antigens(donor) <= antigens(recipient))


@pytest.mark.parametrize(
    "requested", list(B), ids=[blood_type.value for blood_type in B]
)
def test_the_table_matches_the_document(requested):
    assert compatible_donor_types(requested) == DOCUMENT_TABLE[requested]


def test_o_negative_can_give_to_everyone():
    assert all(is_compatible(B.O_NEG, requested) for requested in B)


def test_ab_positive_can_receive_from_everyone():
    assert compatible_donor_types(B.AB_POS) == frozenset(B)


@pytest.mark.parametrize(
    "blood_type", list(B), ids=[blood_type.value for blood_type in B]
)
def test_every_type_is_compatible_with_itself(blood_type):
    assert is_compatible(blood_type, blood_type)


def test_the_compatible_types_cannot_be_changed_by_accident():
    assert isinstance(compatible_donor_types(B.A_POS), frozenset)
