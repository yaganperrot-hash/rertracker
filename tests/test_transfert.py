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
