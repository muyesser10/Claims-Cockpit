"""Tests for the Turkish sentence splitter."""

from worker.parser.sentence_splitter import split


def test_basic_split():
    """Splits on real sentence boundaries."""
    result = split("Merhaba. Nasılsın?")
    assert result == ["Merhaba.", "Nasılsın?"]


def test_abbreviation_not_split():
    """Abbreviations like 'Sn.' do not end a sentence."""
    result = split("Dün Sn. Ahmet aradı. Aracı hasar gördü.")
    assert result == ["Dün Sn. Ahmet aradı.", "Aracı hasar gördü."]


def test_decimal_not_split():
    """Decimals like '3.5' do not end a sentence."""
    result = split("Aracı 3.5 saatte geldi. Hasar büyük.")
    assert result == ["Aracı 3.5 saatte geldi.", "Hasar büyük."]


def test_exclamation_and_question():
    """Splits on ! and ? as well as period."""
    result = split("Kaza oldu! Ne yapmalıyım? Bilmiyorum.")
    assert result == ["Kaza oldu!", "Ne yapmalıyım?", "Bilmiyorum."]


def test_empty_sentences_dropped():
    """Trailing whitespace/periods don't produce empty sentences."""
    result = split("Tek cümle.   ")
    assert result == ["Tek cümle."]
