from apps.search.services import _join, highlight


def test_search_markup_escapes_database_text():
    text = "<script>alert(1)</script>"

    assert str(_join(text)) == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert str(highlight(text, "alert")) == (
        "&lt;script&gt;<mark>alert</mark>(1)&lt;/script&gt;"
    )
