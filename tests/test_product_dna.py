from memory_permanent.product_dna import public_identity, response_headers


def test_product_dna_manifest_is_present_and_first_party():
    identity = public_identity()
    assert identity["schema"] == "memoria-permanente.product-dna.v2"
    assert identity["product_id"] == "memoria-permanente"
    assert identity["manufacturer"] == "MEMORIA_PERMANENTE_IA_SISTEMAS"
    assert identity["manufacturer_project_id"] == "memoria-permanente"
    assert identity["trust_class"] == "FIRST_PARTY_SOVEREIGN"
    assert len(identity["dna_sha256"]) == 64


def test_product_dna_response_headers_match_public_identity():
    identity = public_identity()
    headers = response_headers()
    assert headers["X-WMCP-Product-ID"] == identity["product_id"]
    assert headers["X-WMCP-Product-DNA"] == identity["dna_sha256"]
    assert headers["X-WMCP-Manufacturer"] == identity["manufacturer"]
