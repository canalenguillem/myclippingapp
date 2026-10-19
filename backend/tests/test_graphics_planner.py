import pytest

from app.services import graphics_planner as gp

TEXT = ("Hay muchos pensionistas en España, cada vez más, hay un sistema de pensiones que no es que vaya a petar, es que ha petado, paga con deuda, "
        "se saca dinero de todos lados para poder pagar las pensiones que son la mitad del gasto público en España. Dicen no, con los inmigrantes sí, "
        "están publicando ya informes en Funcas que te cuentan que no da. Ese es un asunto que sí que funciona electoralmente para el PSOE.")


def words(text=TEXT, step=0.36):
    return [{"text": w, "start": round(i * step, 3), "end": round(i * step + 0.3, 3)} for i, w in enumerate(text.split())]


def idx(ws, needle):
    return next(i for i, w in enumerate(ws) if needle in w["text"].lower())


def run(ws, llm, **kw):
    base = dict(words=ws, duration=ws[-1]["end"], hook="", assets=[], existing=[], cortinilla_at=None, single_lane=False)
    return gp.plan(**{**base, **kw}, llm=llm)


# --- plan B ---------------------------------------------------------------------------------------------

def test_dictionary_picks_things_not_groups_and_spaces_them_out():
    ws = words()
    beats = gp.from_dictionary(ws, ws[-1]["end"])
    emojis = [b["emoji"] for b in beats]
    assert "🧓" in emojis and "💥" in emojis and len(beats) >= 2        # «deuda» queda a menos de 4,5 s de «petado»: no entra
    assert not any(b["emoji"] in "🇪🇸👨👩" for b in beats) and len(beats) <= gp.max_beats(ws[-1]["end"])
    assert all(b["at"] == next(w["start"] for w in ws if w["start"] == b["at"]) for b in beats)       # el tiempo es el de una palabra real
    assert all(b2["at"] - b1["at"] >= 4.5 for b1, b2 in zip(beats, beats[1:]))
    boom = next(b for b in beats if b["emoji"] == "💥")
    assert boom["effect"] == "explode" and "peta" in boom["reason"]
    assert len({b["emoji"] for b in beats}) == len(beats)                                              # sin repetir emoji


def test_dictionary_ignores_short_words_and_unknown_text():
    assert gp.from_dictionary(words("la el de un y o sin nada especial aquí", 1.0), 10.0) == []
    assert gp.from_dictionary([], 10.0) == []


# --- modelo ---------------------------------------------------------------------------------------------

def test_model_beats_are_anchored_to_the_chosen_word_and_validated():
    ws = words()
    i_pen, i_peta, i_inm = idx(ws, "pensionistas"), idx(ws, "petado"), idx(ws, "inmigrantes")
    raw = {"beats": [
        {"word_index": i_pen, "motif": "emoji", "emoji": "🧓", "reason": "pensionistas"},
        {"word_index": i_peta, "motif": "emoji", "emoji": "💥", "effect": "explode", "reason": "ha petado"},
        {"word_index": i_inm, "motif": "emoji", "emoji": "👳🏽", "reason": "colectivo"},                 # tono de piel: se descarta
        {"word_index": 9999, "motif": "emoji", "emoji": "🔥"}, {"word_index": "3", "motif": "emoji", "emoji": "🔥"},
        {"word_index": 4, "motif": "keyword", "text": "  "}, {"word_index": 5, "motif": "otro"}, "basura",
        {"word_index": i_inm + 1, "motif": "emoji", "emoji": "🇫🇷"}, {"word_index": i_inm + 2, "motif": "emoji", "emoji": "abc"},
    ]}
    plan = run(ws, lambda s, u: raw)
    assert plan.source == "model"
    assert [(b["type"], b["emoji"]) for b in plan.beats] == [("emoji", "🧓"), ("emoji", "💥")]
    assert plan.beats[0]["at"] == ws[i_pen]["start"] and plan.beats[1]["effect"] == "explode" and plan.beats[1]["reason"] == "ha petado"
    assert not any("tono" in str(b) for b in plan.beats)


def test_flags_and_skin_tones_are_filtered_but_spain_is_allowed():
    assert gp.emoji_allowed("🇪🇸") and gp.emoji_allowed("🧓") and gp.emoji_allowed("🗳️")
    assert not gp.emoji_allowed("🇫🇷") and not gp.emoji_allowed("👍🏽")


def test_image_beats_need_an_asset_of_the_library_and_use_valid_options():
    ws = words()
    i = idx(ws, "deuda")
    good = {"beats": [{"word_index": i, "motif": "image", "asset_id": 7, "style": "card", "entry": "punch", "effect": "explode"}]}
    plan = run(ws, lambda s, u: good, assets=[{"id": 7, "name": "guante", "tags": []}])
    assert plan.beats[0]["type"] == "image" and plan.beats[0]["asset_id"] == 7 and (plan.beats[0]["entry"], plan.beats[0]["effect"]) == ("punch", "explode")
    inv = run(ws, lambda s, u: {"beats": [{"word_index": i, "motif": "image", "asset_id": 99}]}, assets=[{"id": 7, "name": "guante", "tags": []}])
    assert inv.source == "plan_b"                                                          # asset inexistente: nada válido → plan B
    odd = run(ws, lambda s, u: {"beats": [{"word_index": i, "motif": "image", "asset_id": 7, "style": "raro", "entry": "volar", "effect": "arder"}]},
              assets=[{"id": 7, "name": "guante", "tags": []}])
    assert odd.beats[0]["style"] == "card" and "entry" not in odd.beats[0] and "effect" not in odd.beats[0]


def test_prompt_has_the_words_the_assets_and_the_limits():
    seen = {}
    ws = words()
    run(ws, lambda s, u: seen.update(system=s, user=u) or {"beats": []}, assets=[{"id": 3, "name": "hucha", "tags": ["dinero"]}], hook="Gancho X")
    assert f"Como máximo {gp.max_beats(ws[-1]['end'])} beats" in seen["system"] and "NUNCA emojis de personas" in seen["system"]
    assert "3: hucha [dinero]" in seen["user"] and "Gancho X" in seen["user"] and "0(0.0)Hay" in seen["user"]


def test_the_user_beats_win_and_proposals_never_overlap_them():
    ws = words()
    i = idx(ws, "pensionistas")
    mine = [{"type": "emoji", "at": ws[i]["start"], "emoji": "🔥"}]
    raw = {"beats": [{"word_index": i, "motif": "emoji", "emoji": "🧓"}, {"word_index": idx(ws, "deuda"), "motif": "emoji", "emoji": "💸"}]}
    plan = run(ws, lambda s, u: raw, existing=mine)
    assert [b["emoji"] for b in plan.beats] == ["💸"]                                      # el 🧓 solapa con tu 🔥 (mismo tipo); el 💸 cabe
    assert any("no cabe" in n for n in plan.notes)


def test_respects_the_cortinilla_the_hook_and_single_lane():
    ws = words()
    i_first, i_peta = 2, idx(ws, "petado")
    raw = {"beats": [{"word_index": i_first, "motif": "keyword", "text": "HAY"}, {"word_index": i_peta, "motif": "emoji", "emoji": "💥"}]}
    plan = run(ws, lambda s, u: raw, cortinilla_at=ws[i_peta]["start"] + 0.2)               # la cortinilla cae justo tras «petado»
    assert all(not (b["at"] - b["lead"] < ws[i_peta]["start"] + 0.2 < b["at"] - b["lead"] + b["duration"]) for b in plan.beats)
    assert all(b["at"] >= 2.2 for b in plan.beats if b["type"] == "keyword")                # el gancho ocupa los primeros 2,2 s
    two = run(ws, lambda s, u: {"beats": [{"word_index": 10, "motif": "keyword", "text": "A"}, {"word_index": 11, "motif": "emoji", "emoji": "🔥"}]}, single_lane=True)
    assert len(two.beats) == 1


def test_no_model_falls_back_with_a_note_and_the_limit_holds():
    ws = words()
    for llm in (None, lambda s, u: None, lambda s, u: {"beats": "no es lista"}, lambda s, u: {"beats": []}):
        plan = run(ws, llm)
        assert plan.source == "plan_b" and plan.notes and 0 < len(plan.beats) <= gp.max_beats(ws[-1]["end"])
    many = {"beats": [{"word_index": 8 + 12 * k, "motif": "emoji", "emoji": e} for k, e in enumerate("🔥💰😱👀🚨✅❌")]}
    assert len(run(ws, lambda s, u: many).beats) <= gp.max_beats(ws[-1]["end"])


def test_default_llm_needs_a_key(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    assert gp.default_llm("s", "u") is None


# --- mapas de países ------------------------------------------------------------------------------------

def test_mentions_find_countries_multiword_names_and_europe():
    from app.services import country_maps
    ws = words("Francia y Estados Unidos hablan de Europa, pero los europeos y la India no. Otra vez Francia.")
    assert [n for n, _ in country_maps.mentions(ws)] == ["Francia", "Estados Unidos", "Europa", "India"]   # una vez cada uno; «europeos» no es «Europa»
    assert dict(country_maps.mentions(ws))["Francia"] == 0
    assert country_maps.mentions(words("Nada de países aquí")) == []


def test_plan_adds_the_map_at_the_first_mention_unless_the_model_already_did():
    ws = words("Hoy hablamos hoy de Francia, que debe mucho dinero, y luego de Italia que tampoco paga nada y así seguimos hasta el final del vídeo.", step=1.0)
    out = run(ws, lambda s, u: {"beats": []}, maps={"Francia": 7, "Italia": 8})
    imgs = [b for b in out.beats if b["type"] == "image"]
    assert [(b["asset_id"], b["at"], b["style"]) for b in imgs] == [(7, 4.0, "original"), (8, 12.0, "original")]
    model = lambda s, u: {"beats": [{"word_index": 4, "motif": "image", "asset_id": 7, "style": "card", "reason": "mapa"}]}
    out2 = run(ws, model, assets=[{"id": 7, "name": "Mapa de Francia", "tags": []}], maps={"Francia": 7})
    assert [b["style"] for b in out2.beats if b["type"] == "image"] == ["card"]   # el del modelo no se duplica


def test_model_counter_and_strike_beats_are_validated():
    ws = words("El déficit llegó a 700 millones y el PSOE lo niega todo.", step=1.0)
    ok = gp.beat_from_model({"word_index": 4, "motif": "counter", "to_value": 700, "suffix": " M€", "label": " déficit ", "reason": "cifra"}, ws, set())
    assert ok == {"at": 4.0, "reason": "cifra", "type": "counter", "from_value": 0.0, "to_value": 700.0, "suffix": " M€", "label": "déficit"}
    for bad in ({"to_value": "mucho"}, {"to_value": True}, {"to_value": 1e12}, {"to_value": 5, "from_value": "x"}, {}):
        assert gp.beat_from_model({"word_index": 4, "motif": "counter", **bad}, ws, set()) is None, bad
    assert gp.beat_from_model({"word_index": 8, "motif": "strike", "text": " psoe "}, ws, set())["text"] == "PSOE"
    assert gp.beat_from_model({"word_index": 8, "motif": "strike", "text": " "}, ws, set()) is None


def test_speaker_beats_name_each_known_speaker_once_after_the_hook_and_a_real_turn():
    def w(text, start, speaker):
        return {"text": text, "start": start, "end": start + 0.4, "speaker": speaker}
    ws = [w("hola", 0.0, "A"), w("a", 0.5, "A"), w("todos", 1.0, "A"), w("sí", 1.5, "B"), w("claro", 2.0, "A"), w("vamos", 2.5, "A"),
          w("con", 3.0, "A"), w("ello", 3.5, "A"), w("bien", 4.0, "B"), w("gracias", 4.5, "B"), w("mucho", 5.0, "B"), w("más", 5.5, "B")]
    cards = {"A": {"name": "Ana López", "role": "periodista"}, "B": {"name": "", "role": ""}, "C": {"name": "Sin voz"}}
    out = gp.speaker_beats(ws, cards)
    assert out == [{"type": "lower_third", "at": 3.0, "name": "Ana López", "role": "periodista", "priority": 8, "reason": "«Ana López» habla"}]
    assert gp.speaker_beats(ws, {"B": {"name": "Beto"}})[0]["at"] == 4.0           # B: turno real desde los 4,0 s, ya tras el gancho
    assert gp.speaker_beats(ws, {}) == []


def test_plan_includes_the_speaker_lower_third():
    ws = words("uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis", step=1.0)
    for x in ws:
        x["speaker"] = "A"
    out = run(ws, lambda s, u: {"beats": []}, speakers={"A": {"name": "Ana López", "role": "periodista"}})
    lt = [b for b in out.beats if b["type"] == "lower_third"]
    assert len(lt) == 1 and lt[0]["name"] == "Ana López" and lt[0]["role"] == "periodista" and lt[0]["at"] >= 2.6
