from app.services import seo




# --- @ del canal original y enlace al vídeo ----------------------------------------------------------------

def test_normalize_handle_accepts_variants_and_rejects_junk():
    for text in ("esRadio", "@esRadio", " @esRadio ", "https://www.youtube.com/@esRadio", "https://www.youtube.com/@esRadio/videos?x=1"):
        assert seo.normalize_handle(text) == "@esRadio", text
    assert seo.normalize_handle("") == "" and seo.normalize_handle("dos palabras") == "" and seo.normalize_handle("<b>") == ""
    assert seo.handle_from_info({"uploader_id": "@esRadio"}) == "@esRadio"
    assert seo.handle_from_info({"uploader_id": "UC123", "channel_url": "https://www.youtube.com/channel/UC123"}) == ""
    assert seo.handle_from_info({"uploader_url": "https://www.youtube.com/@Salud-Senior"}) == "@Salud-Senior"


def test_source_link_points_to_the_clip_start_and_with_source_puts_the_handle_first_without_repeating():
    assert seo.source_link("https://www.youtube.com/watch?v=abcdefghijk&list=x", 98.7) == "https://www.youtube.com/watch?v=abcdefghijk&t=98s"
    assert seo.source_link("https://youtu.be/abcdefghijk?si=1", 0) == "https://www.youtube.com/watch?v=abcdefghijk&t=0s"
    assert seo.source_link("https://otro.com/v/1", 5) == "https://otro.com/v/1"
    out = seo.with_source("Texto\n\n#Shorts", handle="@esRadio", url="https://youtu.be/abcdefghijk", start=98)
    assert out == "@esRadio\nVídeo original: https://www.youtube.com/watch?v=abcdefghijk&t=98s\n\nTexto\n\n#Shorts"
    assert seo.with_source(out, handle="@esRadio", url="https://youtu.be/abcdefghijk", start=98) == out          # no se duplica
    assert seo.with_source("Texto", handle="", url="https://youtu.be/abcdefghijk", start=3).startswith("Vídeo original: ")
