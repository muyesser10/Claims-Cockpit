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


# --- Turkish-charactered names (S2-5) ----------------------------------------


def test_turkish_charactered_name_is_masked():
    """A name written with Turkish characters still matches the ASCII dictionary."""
    masked, mappings = mask_names("Hüseyin aradi")
    assert "[NAME_1]" in masked
    assert "Hüseyin" not in masked
    assert mappings[0]["real_value"] == "Hüseyin"


def test_various_turkish_charactered_names_matched():
    masked, mappings = mask_names("Ömer, Şeyma, Çağrı ve Gökhan geldi")
    assert masked.count("[NAME_") == 4
    assert len(mappings) == 4


def test_original_text_preserved_not_folded():
    """Only the matched name becomes a placeholder — surrounding Turkish
    words (e.g. "dün") keep their original characters, they are never
    replaced by the ASCII-folded form used internally for comparison."""
    masked, mappings = mask_names("Hüseyin dün geldi")
    assert masked == "[NAME_1] dün geldi"
    assert mappings[0]["real_value"] == "Hüseyin"


def test_ascii_name_still_matched_regression():
    """Plain ASCII dictionary entries (the v0 set) still match unchanged."""
    masked, mappings = mask_names("Ahmet geldi")
    assert "[NAME_1]" in masked
    assert mappings[0]["real_value"] == "Ahmet"


# --- Dictionary expansion (turkish_names.txt) --------------------------------


def test_name_from_turkish_names_file_is_masked():
    """A name that only exists in data/dictionaries/turkish_names.txt (not
    in the original v0 set) is matched too — confirms the file was loaded
    into COMMON_NAMES."""
    masked, mappings = mask_names("Abdulkadir aradi")
    assert "[NAME_1]" in masked
    assert mappings[0]["real_value"] == "Abdulkadir"


# --- Ambiguous names: surname / context gating (S2-5) ------------------------


def test_ambiguous_name_with_surname_neighbor_is_masked():
    """ "Deniz" collides with the everyday word "deniz" (sea), but a
    following surname is real evidence it's a name here."""
    masked, mappings = mask_names("Deniz Yilmaz aradi")
    assert "[NAME_1]" in masked
    assert "Deniz" not in masked
    assert mappings[0]["real_value"] == "Deniz"


def test_ambiguous_name_with_context_marker_sayin_is_masked():
    masked, mappings = mask_names("Sayin Deniz, hasar bildiriyorum")
    assert "[NAME_1]" in masked
    assert "Deniz" not in masked


def test_ambiguous_name_with_context_marker_ad_soyad_is_masked():
    masked, mappings = mask_names("Ad Soyad: Deniz hasar formu")
    assert "[NAME_1]" in masked


def test_ambiguous_name_without_evidence_is_not_masked():
    """No surname neighbor, no context marker — "yagmur" (rain) stays a
    plain word, not a name."""
    masked, mappings = mask_names("Yagmur yagdi dun")
    assert masked == "Yagmur yagdi dun"
    assert mappings == []


def test_non_ambiguous_name_still_masked_unconditionally():
    """A COMMON_NAMES entry that is NOT in AMBIGUOUS_NAMES is masked
    regardless of neighbors — the ambiguous-name gate must not affect it."""
    masked, mappings = mask_names("Ahmet aradi")
    assert "[NAME_1]" in masked
    assert mappings[0]["real_value"] == "Ahmet"
