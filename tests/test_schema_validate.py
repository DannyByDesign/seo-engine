"""Tests for scripts.lib.schema_validate: offline JSON-LD validation against
Google's rich-result severity model (extruct is a real dependency here, no
mocking of extraction itself)."""

from __future__ import annotations

from scripts.lib import schema_validate as sv

URL = "https://mysite.org/page"


def ld_html(payload: str) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{payload}</script>'
        "</head><body></body></html>"
    )


def test_article_missing_image_and_date_published_is_warnings_not_errors():
    html = ld_html(
        '{"@context":"https://schema.org","@type":"Article","headline":"Title"}'
    )
    result = sv.validate_html(html, URL)
    assert result.ok is True
    assert result.counts() == {"error": 0, "warning": 1, "info": 0}
    warning = result.issues[0]
    assert warning.severity == "warning"
    assert warning.node_type == "Article"
    assert "image" in warning.message
    assert "datePublished" in warning.message


def test_product_missing_name_is_error_and_not_ok():
    html = ld_html('{"@context":"https://schema.org","@type":"Product"}')
    result = sv.validate_html(html, URL)
    assert result.ok is False
    errors = [i for i in result.issues if i.severity == "error"]
    assert len(errors) == 1
    assert "name" in errors[0].message
    assert errors[0].node_type == "Product"


def test_empty_string_required_value_counts_as_missing():
    html = ld_html('{"@context":"https://schema.org","@type":"Product","name":""}')
    result = sv.validate_html(html, URL)
    assert result.ok is False
    errors = [i for i in result.issues if i.severity == "error" and i.node_type == "Product"]
    assert len(errors) == 1
    assert "name" in errors[0].message


def test_whitespace_only_required_value_counts_as_missing():
    html = ld_html('{"@context":"https://schema.org","@type":"Product","name":"   "}')
    result = sv.validate_html(html, URL)
    assert result.ok is False


def test_empty_list_required_value_counts_as_missing():
    html = ld_html(
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}'
    )
    result = sv.validate_html(html, URL)
    assert result.ok is False
    assert any("itemListElement" in i.message for i in result.issues if i.severity == "error")


def test_faqpage_valid_markup_yields_info_advisory_not_error_or_warning():
    html = ld_html(
        '{"@context":"https://schema.org","@type":"FAQPage",'
        '"mainEntity":[{"@type":"Question","name":"Q1",'
        '"acceptedAnswer":{"@type":"Answer","text":"A1"}}]}'
    )
    result = sv.validate_html(html, URL)
    assert result.ok is True
    assert result.counts() == {"error": 0, "warning": 0, "info": 1}
    assert result.issues[0].severity == "info"
    assert "retired" in result.issues[0].message.lower()


def test_node_without_type_is_error():
    html = ld_html('{"@context":"https://schema.org","name":"No type here"}')
    result = sv.validate_html(html, URL)
    assert result.ok is False
    assert result.issues[0].node_type == "unknown"
    assert result.issues[0].severity == "error"
    assert "no @type" in result.issues[0].message


def test_graph_unwrapping_extracts_each_node():
    html = ld_html(
        '{"@context":"https://schema.org","@graph":['
        '{"@type":"Organization","name":"Acme"},'
        '{"@type":"WebSite","name":"Acme Site","url":"https://mysite.org"}'
        ']}'
    )
    result = sv.validate_html(html, URL)
    assert result.node_count == 2
    assert result.types_found == ["Organization", "WebSite"]
    assert result.counts() == {"error": 0, "warning": 1, "info": 0}


def test_counts_tallies_across_multiple_nodes():
    html = ld_html(
        "["
        '{"@context":"https://schema.org","@type":"Product"},'
        '{"@context":"https://schema.org","@type":"Article","headline":"H"},'
        '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{"@type":"Question"}]}'
        "]"
    )
    result = sv.validate_html(html, URL)
    counts = result.counts()
    assert counts["error"] >= 1
    assert counts["warning"] >= 1
    assert counts["info"] == 1


def test_no_json_ld_yields_empty_result():
    html = "<html><head><title>No structured data</title></head></html>"
    result = sv.validate_html(html, URL)
    assert result.node_count == 0
    assert result.issues == []
    assert result.ok is True
    assert result.counts() == {"error": 0, "warning": 0, "info": 0}


def test_unrecognized_type_with_no_spec_produces_no_issues():
    html = ld_html('{"@context":"https://schema.org","@type":"SomeUnknownType"}')
    result = sv.validate_html(html, URL)
    assert result.ok is True
    assert result.types_found == ["SomeUnknownType"]
    assert result.issues == []
