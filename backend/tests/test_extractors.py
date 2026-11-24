import codecs

from app import extractors as ex


def test_bom_decoding():
    assert ex.decode_text(codecs.BOM_UTF8 + "héllo".encode()) == "héllo"
    assert ex.decode_text("hi there".encode("utf-16")) == "hi there"
    assert "\ufffd" in ex.decode_text(b"bad \xff byte")


def test_summary_skips_headers_and_numbers():
    text = "# Title\n2026-11-24\n12345\nShort\nThe quarterly review went well. Sales grew by ten percent.\nMore text follows here."
    assert ex.fallback_summary(text) == "The quarterly review went well. Sales grew by ten percent."
    assert len(ex.fallback_summary("word " * 500)) <= 300


def test_keywords_clean_and_cap():
    kws, src = ex.clean_keywords(["standing desk, ergonomic chairs", "billing@example.com", "+1 555-0142"],
                                 "invoice invoice chairs desk northwind northwind supplies total standing ergonomic")
    assert len(kws) <= 6 and not any("@" in k or "555" in k for k in kws)
    assert "standing desk" in kws and src == "model+freq"
    assert ex.clean_keywords(None, "zeppelin zeppelin balloon")[0][0] == "zeppelin"


SRC = "Invoice from Northwind. Bread 2.80 and milk. Standing desk, chairs, supplies, invoice total."


def test_keywords_ungrounded_dropped():
    kws, src = ex.clean_keywords(["Bread $2.80 miljard", "standing desk"], SRC)
    assert "Bread $2.80 miljard" not in kws and "standing desk" in kws and src == "model+freq"


def test_keywords_too_long_dropped():
    long30 = "northwind invoice supplies total"  # grounded, 32 chars
    five = "standing desk chairs supplies total"  # grounded, 5 words
    kws, src = ex.clean_keywords([long30, five], SRC)
    assert long30 not in kws and five not in kws and src == "freq"


def test_keywords_topup_and_cap_no_dupes():
    kws, src = ex.clean_keywords(["invoice", "Invoice", "miljard"], SRC)
    assert kws[0] == "invoice" and len(kws) == 6 and len({k.lower() for k in kws}) == 6
    assert "miljard" not in kws and src == "model+freq"


def test_broken_pdf_is_error_and_title_fallback(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a pdf")
    try:
        ex.read_pdf(p, 3)
        assert False
    except ex.ExtractError:
        pass
    assert ex.title_from_name("my_report-final.txt") == "My report final"
