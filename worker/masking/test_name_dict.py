# worker/masking/test_name_dict.py
"""Tests for dictionary-based name masking."""

from worker.masking.name_dict import mask_names


def test_name_is_masked():
    """A known first name is masked."""
    masked, mappings = mask_names("Dun Ahmet aradi")
    assert "[NAME_1]" in masked
    assert "Ahmet" not in masked
    assert mappings[0]["pii_type"] == "NAME"


def test_non_name_word_kept():
    """Ordinary words are left untouched."""
    masked, mappings = mask_names("Araba hasar gordu")
    assert masked == "Araba hasar gordu"
    assert mappings == []


def test_name_with_punctuation():
    """A name followed by punctuation is masked, punctuation kept."""
    masked, mappings = mask_names("Merhaba Mehmet, nasilsin")
    assert "[NAME_1]," in masked
    assert "Mehmet" not in masked


def test_case_insensitive():
    """Names are matched regardless of case."""
    masked, mappings = mask_names("AYSE ve ali geldi")
    assert masked.count("[NAME_") == 2
    assert len(mappings) == 2


def test_counter_continues():
    """start_counter continues numbering from a previous pass."""
    masked, mappings = mask_names("Ali geldi", start_counter=3)
    assert "[NAME_4]" in masked
