import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db.models import Asset
from app.services import assets as assets_service
from app.services import storage
from tests.test_clips_api import _clip, _login, _project


def png(size=(100, 80), color=(200, 30, 20, 255), box=None, mode="RGBA", fmt="PNG"):
    img = Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else color[:3])
    if box:
        img.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color), box[:2])
    elif mode == "RGBA":
        img.paste(Image.new("RGBA", size, color))
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def upload(client, h, data, name="hucha.png", form_name=None, ctype="image/png"):
    return client.post("/api/assets", files={"file": (name, data, ctype)}, data={"name": form_name} if form_name is not None else {}, headers=h)


def test_process_upload_normalizes_to_png_crops_transparency_and_limits_size():
    out, w, h = assets_service.process_upload(png((400, 300), box=(150, 100, 250, 200)))
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and (w, h) == img.size and w <= 110 and h <= 110   # recortado a la caja visible (100x100) más margen
    big, bw, bh = assets_service.process_upload(png((3000, 1500)))
    assert max(bw, bh) == assets_service.MAX_SIDE and bw == 2 * bh
    jpg, jw, jh = assets_service.process_upload(png((50, 50), mode="RGB", fmt="JPEG"))
    assert (jw, jh) == (50, 50) and Image.open(io.BytesIO(jpg)).mode == "RGBA"
    webp, *_ = assets_service.process_upload(png((50, 50), fmt="WEBP"))
    assert Image.open(io.BytesIO(webp)).format == "PNG"


@pytest.mark.parametrize("data,msg", [(b"", "vacío"), (b"no soy una imagen", "No se pudo leer"), (png(fmt="GIF"), "PNG, JPG o WebP"),
                                      (png((50, 50), color=(0, 0, 0, 0)), "transparente"), (b"x" * (assets_service.MAX_BYTES + 1), "pesa")])
def test_process_upload_rejects_bad_files(data, msg):
    with pytest.raises(assets_service.AssetError, match=msg):
        assets_service.process_upload(data)


def test_exif_and_metadata_are_dropped():
    img = Image.new("RGB", (40, 40), "red")
    exif = Image.Exif()
    exif[0x010E] = "descripción privada"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    processed, *_ = assets_service.process_upload(out.getvalue())
    assert not Image.open(io.BytesIO(processed)).getexif()


def test_upload_list_rename_delete(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    r = upload(client, h, png((100, 80)), name="mi_hucha.png")
    assert r.status_code == 201
    a = r.json()
    assert a["name"] == "mi_hucha" and (a["width"], a["height"]) == (100, 80) and a["url"].startswith("/api/media/")
    assert client.get(a["url"]).status_code == 200                                # la URL firmada sirve la imagen
    assert (tmp_path / f"u{db.get(Asset, a['id']).user_id}" / "assets" / f"{a['id']}.png").is_file()
    assert upload(client, h, png(), form_name="Hucha cerdito").json()["name"] == "Hucha cerdito"
    assert [x["id"] for x in client.get("/api/assets").json()][0] > a["id"]       # más recientes primero
    out = client.patch(f"/api/assets/{a['id']}", json={"name": " Hucha ", "tags": ["dinero", " ", "ahorro"]}, headers=h).json()
    assert out["name"] == "Hucha" and out["tags"] == ["dinero", "ahorro"]
    assert client.delete(f"/api/assets/{a['id']}", headers=h).status_code == 204
    assert not (tmp_path / f"u1" / "assets" / f"{a['id']}.png").exists() and len(client.get("/api/assets").json()) == 1


def test_upload_rejects_non_images_with_a_clear_message(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    r = upload(client, h, b"MZ\x90\x00 ejecutable", name="virus.png")
    assert r.status_code == 422 and "No se pudo leer" in r.json()["detail"]
    assert upload(client, h, png(fmt="GIF"), name="a.gif", ctype="image/gif").status_code == 422
    assert client.get("/api/assets").json() == []


def test_a_used_asset_cannot_be_deleted_until_its_graphics_are_removed(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = upload(client, h, png()).json()
    c = _clip(db, p, graphics_json=[{"type": "image", "at": 5.0, "asset_id": a["id"]}])
    r = client.delete(f"/api/assets/{a['id']}", headers=h)
    assert r.status_code == 409 and "1 clip" in r.json()["detail"]
    c.graphics_json = []
    db.commit()
    assert client.delete(f"/api/assets/{a['id']}", headers=h).status_code == 204


def test_assets_are_isolated_between_users(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = upload(client, h, png()).json()
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.get("/api/assets").json() == []
    assert other.patch(f"/api/assets/{a['id']}", json={"name": "x"}, headers=hb).status_code == 404
    assert other.delete(f"/api/assets/{a['id']}", headers=hb).status_code == 404
    assert TestClient(client.app).post("/api/assets", files={"file": ("a.png", png(), "image/png")}).status_code in (401, 403)


def test_country_maps_are_generated_once_and_listed(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    countries = client.get("/api/assets/maps/countries").json()
    assert {"name": "Francia", "group": "Europa"} in countries and {"name": "Marruecos", "group": "Otros"} in countries
    r = client.post("/api/assets/maps", json={"countries": ["Francia", "Italia", "Francia"]}, headers=h)
    assert r.status_code == 201 and [a["name"] for a in r.json()] == ["Mapa de Francia", "Mapa de Italia"]
    assert all(a["kind"] == "map" and a["width"] > 100 and client.get(a["url"]).status_code == 200 for a in r.json())
    again = client.post("/api/assets/maps", json={"countries": ["Francia", "Portugal"]}, headers=h).json()
    assert [a["name"] for a in again] == ["Mapa de Portugal"]                      # Francia ya estaba
    assert len(client.get("/api/assets").json()) == 3


def test_country_maps_reject_unknown_country(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    r = client.post("/api/assets/maps", json={"countries": ["Atlantida"]}, headers=h)
    assert r.status_code == 422 and "Atlantida" in r.json()["detail"]
    assert client.get("/api/assets").json() == []


def test_every_listed_country_renders():
    from app.services import country_maps
    for c in country_maps.available():
        assert country_maps.render(c["name"])[:4] == b"\x89PNG"
