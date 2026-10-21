from mini_ki import braucht_kontext, gesperrt


def test_gesperrt_email_telefon_iban():
    assert gesperrt("ada@example.com") is True
    assert gesperrt("Die Adresse ist ada@example.com bitte.") is True
    assert gesperrt("+49 151 23456789") is True
    assert gesperrt("DE89370400440532013000") is True
    assert gesperrt("Ist Avatari DSGVO-konform?") is False
    assert gesperrt("Wie erreiche ich Avatari?") is False
    assert gesperrt("") is False


def test_braucht_kontext():
    assert braucht_kontext("Ja, ich möchte mehr darüber erfahren") is True
    assert braucht_kontext("Ist Avatari DSGVO-konform?") is False
    assert braucht_kontext("Gib mir den Kontakt dazu") is True
    assert braucht_kontext("Ja") is True
    lang = "Ja " + " ".join(["wort"] * 20)
    assert len(lang.split()) > 14
    assert braucht_kontext(lang) is False
    assert braucht_kontext("") is False
