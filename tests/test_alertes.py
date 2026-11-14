"""Alertes Telegram : déclencheur, anti-spam, état persistant, texte du post, envoi (sans réseau)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote

import pytest

from backend import alertes
from backend.alertes import (
    LONGUEUR_MAX, Candidat, Obs, autorisees, composer_texte, en_silence, envoyer_telegram, evaluer, hashtag,
    lien_x, lire_etat, noter_envoi, rejouer, verifier_alertes,
)
from backend.config import Settings
from backend.metrics import cout_eur

PARIS = alertes.PARIS_TZ
# 1 € = 60/12,31 ≈ 4,87 minutes-voyageurs : 30 000 mv ≈ 6 155 €
S = Settings(alerte_seuil_euros=6000, alerte_duree_incident_min=30, alerte_ratio_seuil_incident=0.5,
             alerte_fenetre_min=60, alerte_max_jour=2, alerte_delai_ligne_h=3,
             alerte_silence_debut=22, alerte_silence_fin=6, smic_horaire=12.31,
             telegram_bot_token="TOKEN", telegram_chat_id="42")


def paris(h, m=0, jour=10):
    return datetime(2026, 11, jour, h, m, tzinfo=PARIS).astimezone(timezone.utc)


def obs(line="RER_D", quand=None, duree=5, mv=1000, gare="Juvisy", supprime=False):
    return Obs(line, quand or paris(8, 30), duree, mv, gare, supprime)


def cand(line="RER_D", euros=7000):
    return Candidat(line, euros, 30000, paris(8), obs(line), "seuil")


# ── Déclencheur ───────────────────────────────────────────

def test_seuil_seul_declenche():
    c = evaluer([obs(mv=15000), obs(mv=15000)], paris(9), S)
    assert [(x.line_id, x.motif) for x in c] == [("RER_D", "seuil")]
    assert c[0].euros == cout_eur(30000, 12.31) >= 6000


def test_sous_le_seuil_rien():
    assert evaluer([obs(mv=20000)], paris(9), S) == []


def test_long_retard_declenche_a_demi_seuil():
    # ≈ 3 100 € : sous le seuil, au-dessus du demi-seuil, avec un train à 34 min
    c = evaluer([obs(mv=15000), obs(duree=34, mv=100)], paris(9), S)
    assert [x.motif for x in c] == ["incident"]


def test_long_retard_sans_cout_ne_declenche_pas():
    assert evaluer([obs(duree=45, mv=5000)], paris(9), S) == []


def test_train_supprime_ne_compte_pas_comme_long_retard():
    assert evaluer([obs(mv=15000), obs(duree=40, mv=100, supprime=True)], paris(9), S) == []


def test_fenetre_glissante_de_60_min():
    vieux = obs(quand=paris(7, 59), mv=40000)        # hors fenêtre à 9 h
    assert evaluer([vieux, obs(quand=paris(8, 1), mv=1000)], paris(9), S) == []
    assert evaluer([vieux], paris(8, 30), S)            # dans la fenêtre à 8 h 30


def test_lignes_triees_par_cout_et_pire_train():
    o = [obs("RER_A", mv=40000), obs("RER_B", mv=60000, gare="Massy"), obs("RER_B", mv=1000, gare="Orsay")]
    c = evaluer(o, paris(9), S)
    assert [x.line_id for x in c] == ["RER_B", "RER_A"]
    assert c[0].pire.gare == "Massy"


# ── Anti-spam ─────────────────────────────────────────────

@pytest.mark.parametrize("h, silence", [(21, False), (22, True), (23, True), (3, True), (5, True), (6, False)])
def test_silence_de_nuit(h, silence):
    assert en_silence(paris(h), S) is silence


def test_rien_la_nuit():
    assert autorisees([cand()], [], paris(22, 30), S) == []


def test_max_deux_par_jour():
    envois = [{"ligne": "RER_A", "quand": paris(8).isoformat()}, {"ligne": "RER_B", "quand": paris(12).isoformat()}]
    assert autorisees([cand("RER_C")], envois, paris(18), S) == []
    # le lendemain, le compteur repart
    assert autorisees([cand("RER_C")], envois, paris(8, jour=11), S)


def test_deux_candidats_le_meme_cycle_respectent_le_plafond():
    envois = [{"ligne": "RER_A", "quand": paris(8).isoformat()}]
    assert [c.line_id for c in autorisees([cand("RER_B"), cand("RER_C")], envois, paris(9), S)] == ["RER_B"]


def test_une_par_ligne_toutes_les_3_h():
    envois = [{"ligne": "RER_D", "quand": paris(8).isoformat()}]
    assert autorisees([cand("RER_D")], envois, paris(10, 59), S) == []
    assert autorisees([cand("RER_D")], envois, paris(11), S)
    assert autorisees([cand("RER_A")], envois, paris(9), S)   # autre ligne : libre


def test_etat_persistant(tmp_path):
    chemin = tmp_path / "alertes" / "etat.json"
    assert lire_etat(chemin) == {"envois": []}
    noter_envoi(chemin, "RER_D", paris(8))
    noter_envoi(chemin, "RER_A", paris(9))
    envois = lire_etat(chemin)["envois"]
    assert [e["ligne"] for e in envois] == ["RER_D", "RER_A"]
    assert autorisees([cand("RER_D")], envois, paris(10), S) == []


def test_etat_purge_apres_7_jours(tmp_path):
    chemin = tmp_path / "etat.json"
    noter_envoi(chemin, "RER_D", paris(8, jour=1))
    noter_envoi(chemin, "RER_A", paris(8, jour=10))
    assert [e["ligne"] for e in lire_etat(chemin)["envois"]] == ["RER_A"]


def test_etat_corrompu_repart_de_zero(tmp_path):
    chemin = tmp_path / "etat.json"
    chemin.write_text("{pas du json", encoding="utf-8")
    assert lire_etat(chemin) == {"envois": []}


# ── Texte ─────────────────────────────────────────────────

def test_texte_du_post():
    c = Candidat("RER_D", 12300, 63_000, paris(7, 40), obs(duree=34, gare="Villeneuve-Saint-Georges"), "seuil")
    assert composer_texte(c, paris(8, 40)) == (
        "RER D, 8h40 : 12 300 € de temps perdu depuis 7h40. 43 jours cumulés. "
        "Retard de 34 min à Villeneuve-Saint-Georges. #RERD")


def test_texte_heures_feminin_et_train_supprime():
    c = Candidat("TRANSILIEN_H", 900, 872, paris(17, 5), obs("TRANSILIEN_H", gare="Persan", supprime=True), "seuil")
    texte = composer_texte(c, paris(18))
    assert "14 h 32 min cumulées. Train supprimé à Persan. #LigneH" in texte


def test_texte_sans_emoji_ni_lien_et_court():
    c = Candidat("RER_B", 9_999_999, 99_999_999, paris(7), obs("RER_B", gare="X" * 300), "seuil")
    texte = composer_texte(c, paris(8))
    assert len(texte) <= LONGUEUR_MAX
    assert texte.endswith("#RERB") and "http" not in texte
    assert all(ord(ch) < 0x2190 or ch in " " for ch in texte)   # pas d'emoji


@pytest.mark.parametrize("ligne, tag", [("RER_A", "#RERA"), ("TRANSILIEN_U", "#LigneU")])
def test_hashtag(ligne, tag):
    assert hashtag(ligne) == tag


def test_lien_x_encode_tout_le_texte():
    texte = "RER D, 8h40 : 12 300 € #RERD"
    lien = lien_x(texte)
    assert lien.startswith("https://x.com/intent/post?text=") and " " not in lien and "#" not in lien
    assert unquote(lien.split("text=")[1]) == texte


# ── Envoi Telegram ────────────────────────────────────────

def _client(status=200):
    http = MagicMock()
    http.post = AsyncMock(return_value=MagicMock(status_code=status, text="{}"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=http)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, http


async def test_envoi_photo_legende_code_et_bouton(tmp_path):
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    ctx, http = _client()
    with patch("httpx.AsyncClient", return_value=ctx):
        assert await envoyer_telegram("RER D <b> 12 € #RERD", image, S) is True
    url, = http.post.await_args.args
    donnees = http.post.await_args.kwargs["data"]
    assert url.endswith("/botTOKEN/sendPhoto")
    assert donnees["chat_id"] == "42" and donnees["parse_mode"] == "HTML"
    assert donnees["caption"] == "<code>RER D &lt;b&gt; 12 € #RERD</code>"
    assert "Ouvrir dans X" in donnees["reply_markup"] and "x.com/intent/post" in donnees["reply_markup"]


async def test_envoi_sans_image_passe_par_sendmessage():
    ctx, http = _client()
    with patch("httpx.AsyncClient", return_value=ctx):
        assert await envoyer_telegram("texte", None, S) is True
    assert http.post.await_args.args[0].endswith("/sendMessage")


async def test_envoi_refuse_ou_reseau_coupe_ne_leve_pas(caplog):
    ctx, _ = _client(status=401)
    with patch("httpx.AsyncClient", return_value=ctx):
        assert await envoyer_telegram("texte", None, S) is False
    with patch("httpx.AsyncClient", side_effect=OSError("réseau")):
        assert await envoyer_telegram("texte", None, S) is False
    assert "TOKEN" not in caplog.text


async def test_sans_token_rien_n_est_envoye():
    sans = S.model_copy(update={"telegram_bot_token": ""})
    with patch("httpx.AsyncClient") as client:
        assert await envoyer_telegram("texte", None, sans) is False
    client.assert_not_called()


# ── Cycle complet ─────────────────────────────────────────

def _cycle(o, envoi_ok=True):
    return (patch("backend.alertes.get_settings", return_value=S),
            patch("backend.alertes._obs_depuis", AsyncMock(return_value=o)),
            patch("backend.alertes.generer_image", AsyncMock(return_value=None)),
            patch("backend.alertes.envoyer_telegram", AsyncMock(return_value=envoi_ok)))


async def test_cycle_envoie_et_retient(tmp_path):
    a, b, c, d = _cycle([obs(mv=40000)])
    with a, b, c, d as envoi:
        assert len(await verifier_alertes(paris(9), dossier=tmp_path)) == 1
        assert await verifier_alertes(paris(9, 5), dossier=tmp_path) == []   # même ligne, < 3 h
    assert envoi.await_count == 1
    assert [e["ligne"] for e in lire_etat(tmp_path / "etat.json")["envois"]] == ["RER_D"]


async def test_cycle_envoi_rate_non_retenu(tmp_path):
    a, b, c, d = _cycle([obs(mv=40000)], envoi_ok=False)
    with a, b, c, d:
        await verifier_alertes(paris(9), dossier=tmp_path)
    assert lire_etat(tmp_path / "etat.json") == {"envois": []}


async def test_cycle_dry_run_n_envoie_rien(tmp_path, capsys):
    a, b, c, d = _cycle([obs(quand=paris(22, 40), mv=1000)])
    with a, b, c, d as envoi:
        textes = await verifier_alertes(paris(23), dry_run=True, dossier=tmp_path)   # même la nuit, même sous le seuil
    envoi.assert_not_called()
    assert len(textes) == 1 and "sous le seuil" in capsys.readouterr().out
    assert not (tmp_path / "etat.json").exists()


async def test_cycle_ne_leve_jamais(tmp_path):
    with patch("backend.alertes.get_settings", return_value=S), \
         patch("backend.alertes._obs_depuis", AsyncMock(side_effect=RuntimeError("base coupée"))):
        assert await verifier_alertes(paris(9), dossier=tmp_path) == []


# ── Backtest ──────────────────────────────────────────────

def test_rejouer_applique_l_anti_spam():
    from datetime import date
    # Une ligne au-dessus du seuil toute la journée : 1 alerte toutes les 3 h, plafonnée à 2
    o = [obs(quand=paris(6) + timedelta(minutes=5 * k), mv=40000) for k in range(12 * 18)]
    jours = rejouer(o, [date(2026, 11, 10)], S)
    alertes_du_jour = jours[date(2026, 11, 10)]
    assert len(alertes_du_jour) == 2
