"""Tests unitaires pour backend/transfert.py : encodage des fichiers de transfert (sans base)"""
import json

from backend.transfert import _ecrire_json, _lire_json

CONTENU = {"jour": "2026-09-15", "incidents": [{"cause": "Motif : défaut d'alimentation électrique"}]}


def test_export_en_utf8_relu_a_l_identique(tmp_path):
    chemin = tmp_path / "incidents.json"
    _ecrire_json(chemin, CONTENU)
    chemin.read_bytes().decode("utf-8")  # lève si le fichier n'est pas en UTF-8
    assert _lire_json(chemin) == CONTENU


def test_ancien_export_windows_cp1252_lu_par_repli(tmp_path, capsys):
    chemin = tmp_path / "incidents.json"
    chemin.write_bytes(json.dumps(CONTENU, ensure_ascii=False).encode("cp1252"))
    assert _lire_json(chemin) == CONTENU
    assert "cp1252" in capsys.readouterr().out


# Bug 46 : un arrêt vu supprimé sur un seul PC n'est pas perdu à l'import
from datetime import datetime, timezone  # noqa: E402

from backend.transfert import arrets_fusionnes  # noqa: E402

P1, P2 = "2026-09-21T06:40:00+00:00", "2026-09-21T06:50:00+00:00"
AVANT, APRES = datetime(2026, 9, 21, 6, 45, tzinfo=timezone.utc), datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc)


def test_arret_supprime_vu_d_un_seul_cote_garde():
    windows = [{"g": "Gare Un", "p": P1, "r": None, "s": True}]
    mac = [{"g": "Gare Un", "p": P1, "r": None, "s": None}, {"g": "Gare Deux", "p": P2, "r": 4, "s": False}]
    fusion = arrets_fusionnes(windows, AVANT, mac, APRES)
    assert [(a["g"], a["s"]) for a in fusion] == [("Gare Un", True), ("Gare Deux", False)]


def test_mesure_la_plus_recente_l_emporte_dans_les_deux_sens():
    windows = [{"g": "Gare Un", "p": P1, "r": None, "s": True}]
    mac = [{"g": "Gare Un", "p": P1, "r": 4, "s": False}]
    assert arrets_fusionnes(windows, AVANT, mac, APRES)[0]["s"] is False   # import plus récent
    assert arrets_fusionnes(mac, APRES, windows, AVANT)[0]["s"] is False   # base plus récente


def test_sans_arrets_d_un_cote():
    mac = [{"g": "Gare Un", "p": P1, "r": 4, "s": False}]
    assert arrets_fusionnes(None, AVANT, mac, APRES) == mac
    assert arrets_fusionnes(mac, APRES, None, AVANT) == mac
