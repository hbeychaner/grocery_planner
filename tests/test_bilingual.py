from app.services.bilingual import BilingualQueryService


def test_bilingual_exact_translation() -> None:
    service = BilingualQueryService()

    cs_term, synonyms = service.translate_to_czech("milk")
    assert cs_term == "mléko"
    assert "čerstvé mléko" in synonyms

    cs_term, _ = service.translate_to_czech("butter")
    assert cs_term == "máslo"

    cs_term, _ = service.translate_to_czech("eggs")
    assert cs_term == "vejce"

    cs_term, _ = service.translate_to_czech("beer")
    assert cs_term == "pivo"


def test_bilingual_compound_phrases() -> None:
    service = BilingualQueryService()

    cs_term, _ = service.translate_to_czech("fresh whole milk")
    assert cs_term == "plnotučné mléko"

    cs_term, _ = service.translate_to_czech("olive oil")
    assert cs_term == "olivový olej"


def test_bilingual_already_czech_term() -> None:
    service = BilingualQueryService()

    cs_term, _ = service.translate_to_czech("máslo")
    assert cs_term == "máslo"

    cs_term, _ = service.translate_to_czech("chléb")
    assert cs_term == "chléb"
