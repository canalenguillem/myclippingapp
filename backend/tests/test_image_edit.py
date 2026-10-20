import io

import pytest
from PIL import Image

from app.db.models import Asset
from app.services import image_edit, storage
from tests.test_clips_api import _login, _project
from tests.test_assets_api import png, upload


def fake_segment(rgb):
    """Máscara de prueba: opaco el cuadrado central, transparente el resto (sin modelo)."""
    w, h = rgb.size
    mask = Image.new("L", rgb.size, 0)
    mask.paste(255, (w // 4, h // 4, w * 3 // 4, h * 3 // 4))
    return mask


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(image_edit, "segment", fake_segment)


def px(img, x, y):
    return img.convert("RGBA").getpixel((x, y))


def test_remove_background_makes_the_outside_transparent_and_keeps_the_inside():
    out = image_edit.remove_background(Image.new("RGB", (100, 100), (200, 30, 20)))
    assert px(out, 5, 5)[3] == 0 and px(out, 50, 50) == (200, 30, 20, 255)


def test_ellipse_and_circle_masks_leave_corners_transparent_and_the_centre_opaque():
    src = Image.new("RGBA", (200, 100), (10, 200, 10, 255))
    e = image_edit.apply_edits(src, shape="ellipse")
    assert e.size == (200, 100) and px(e, 1, 1)[3] == 0 and px(e, 100, 50)[3] == 255
    c = image_edit.apply_edits(src, shape="circle")
    assert c.size == (100, 100) and px(c, 1, 1)[3] == 0 and px(c, 50, 50)[3] == 255 and px(c, 50, 2)[3] > 200   # antialias en el borde


def test_flip_rotate_and_crop_use_known_pixels():
    src = Image.new("RGBA", (40, 20), (0, 0, 255, 255))
    src.putpixel((0, 0), (255, 0, 0, 255))
    assert px(image_edit.apply_edits(src, flip_h=True), 39, 0) == (255, 0, 0, 255)
    assert px(image_edit.apply_edits(src, flip_v=True), 0, 19) == (255, 0, 0, 255)
    r = image_edit.apply_edits(src, rotate=90)
    assert r.size == (20, 40) and px(r, 19, 0) == (255, 0, 0, 255)                   # 90° en sentido horario
    c = image_edit.apply_edits(src, crop={"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5})
    assert c.size == (20, 10) and px(c, 0, 0) == (0, 0, 255, 255)
    for bad in ({"x": 0.9, "y": 0, "w": 0.5, "h": 0.5}, {"x": 0, "y": 0, "w": 0.0, "h": 0.5}):
        with pytest.raises(image_edit.EditError):
            image_edit.apply_edits(src, crop=bad)
    with pytest.raises(image_edit.EditError):
        image_edit.apply_edits(src, shape="estrella")


def make_asset(client, h, size=(200, 200)):
    r = upload(client, h, png(size, color=(200, 30, 20, 255)), name="cara.png")
    assert r.status_code == 201
    return r.json()


def test_rename_validation(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = make_asset(client, h)
    assert client.patch(f"/api/assets/{a['id']}", json={"name": "Sánchez"}, headers=h).json()["name"] == "Sánchez"
    assert client.patch(f"/api/assets/{a['id']}", json={"name": "   "}, headers=h).status_code == 422


def test_preview_does_not_save_and_caches_the_background_removal(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = make_asset(client, h)
    calls = []
    monkeypatch.setattr(image_edit, "segment", lambda rgb: (calls.append(1), fake_segment(rgb))[1])
    r = client.post(f"/api/assets/{a['id']}/preview", json={"remove_bg": True, "shape": "circle"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert img.size[0] == img.size[1] and img.convert("RGBA").getpixel((img.width // 2, img.height // 2))[3] == 255
    client.post(f"/api/assets/{a['id']}/preview", json={"remove_bg": True, "flip_h": True}, headers=h)
    assert len(calls) == 1                                                    # la segunda vez sale de la caché
    assert len(client.get("/api/assets").json()) == 1                         # nada guardado
    assert client.post(f"/api/assets/{a['id']}/preview", json={"rotate": 500}, headers=h).status_code == 422
    assert client.post(f"/api/assets/{a['id']}/preview", json={"crop": {"x": 0.9, "y": 0, "w": 0.5, "h": 0.5}}, headers=h).status_code == 422


def test_edit_copy_and_replace_and_the_in_use_block(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = make_asset(client, h)
    r = client.post(f"/api/assets/{a['id']}/edit", json={"remove_bg": True, "shape": "circle", "name": "Sánchez recortado"}, headers=h)
    assert r.status_code == 201
    copy = r.json()
    assert copy["id"] != a["id"] and copy["name"] == "Sánchez recortado" and copy["width"] == copy["height"]
    assert len(client.get("/api/assets").json()) == 2
    stored = Image.open(storage.absolute(db.get(Asset, copy["id"]).path)).convert("RGBA")
    assert stored.getpixel((stored.width // 2, stored.height // 2))[3] == 255 and stored.getpixel((0, 0))[3] == 0
    default_name = client.post(f"/api/assets/{a['id']}/edit", json={"flip_h": True}, headers=h).json()["name"]
    assert default_name == "cara (editado)"
    rep = client.post(f"/api/assets/{a['id']}/edit", json={"mode": "replace", "rotate": 90, "name": "Girada"}, headers=h)
    assert rep.status_code == 201 and rep.json()["id"] == a["id"] and rep.json()["name"] == "Girada"
    from tests.test_clips_api import _clip
    _clip(db, p, 10.0, 40.0, graphics_json=[{"type": "image", "at": 5.0, "asset_id": a["id"]}])
    assert client.post(f"/api/assets/{a['id']}/edit", json={"mode": "replace", "flip_h": True}, headers=h).status_code == 409
    assert client.post(f"/api/assets/{a['id']}/edit", json={"flip_h": True}, headers=h).status_code == 201     # la copia sí


def test_other_users_cannot_edit_my_images(client, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = make_asset(client, h)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    for path in ("preview", "edit"):
        assert other.post(f"/api/assets/{a['id']}/{path}", json={}, headers=hb).status_code == 404
