"""Alertes Telegram « une ligne dégénère » : image + post X prêt à publier à la main (voir ALERTES.md).

Appelé à la fin de chaque relevé temps réel (main.py, _collect_cycle). Ne lève jamais : une alerte ratée
est journalisée, la collecte continue.

Déclencheur, par ligne, sur les trains relevés dans la fenêtre glissante (alerte_fenetre_min) :
  - coût de la fenêtre ≥ alerte_seuil_euros, ou
  - un train retardé d'au moins alerte_duree_incident_min ET coût ≥ seuil × alerte_ratio_seuil_incident.
Anti-spam : alerte_max_jour par jour, une par ligne sur alerte_delai_ligne_h, silence la nuit ; état persistant
dans publications/alertes/etat.json.

    python -m backend.alertes --dry-run                 # évalue maintenant, affiche, n'envoie rien
    python -m backend.alertes backtest --jours 14       # alertes qu'auraient données les seuils actuels
"""
import argparse
import asyncio
import bisect
import html
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from backend.bot import DOSSIER_PUBLICATIONS, _fmt, _fmt_duree
from backend.config import get_settings

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")
DOSSIER_ALERTES = DOSSIER_PUBLICATIONS / "alertes"
LONGUEUR_MAX = 240
TELEGRAM_API = "https://api.telegram.org"

NOMS = {
    "RER_A": "RER A", "RER_B": "RER B", "RER_C": "RER C", "RER_D": "RER D", "RER_E": "RER E",
    **{f"TRANSILIEN_{l}": f"Ligne {l}" for l in "HJKLNPRU"},
}


def hashtag(line_id: str) -> str:
    """#RERD, #LigneH : les hashtags usuels des comptes de ligne."""
    return "#" + NOMS.get(line_id, line_id).replace(" ", "")


# ── Déclencheur (fonctions pures) ─────────────────────────

@dataclass(frozen=True)
class Obs:
    """Un train retardé ou supprimé, tel que compté par le site (metrics.incident_minutes_voyageurs)."""
    line_id: str
    quand: datetime        # premier relevé (heure_debut), UTC
    duree: int             # pire retard (min), ou attente pour un train supprimé
    mv: int                # minutes-voyageurs
    gare: str | None
    supprime: bool = False


@dataclass(frozen=True)
class Candidat:
    line_id: str
    euros: int
    mv: int
    depuis: datetime       # premier train compté dans la fenêtre
    pire: Obs              # le train qui pèse le plus
    motif: str             # « seuil » ou « incident »


def evaluer(obs: list[Obs], maintenant: datetime, s=None) -> list[Candidat]:
    """Lignes qui déclenchent, la plus coûteuse d'abord. obs : trains relevés (n'importe quand : filtrés ici)."""
    from backend.metrics import cout_eur

    s = s or get_settings()
    debut = maintenant - timedelta(minutes=s.alerte_fenetre_min)
    par_ligne: dict[str, list[Obs]] = defaultdict(list)
    for o in obs:
        if debut < o.quand <= maintenant:
            par_ligne[o.line_id].append(o)

    candidats = []
    for line_id, trains in par_ligne.items():
        mv = sum(o.mv for o in trains)
        euros = cout_eur(mv, s.smic_horaire)
        long_retard = any(not o.supprime and o.duree >= s.alerte_duree_incident_min for o in trains)
        if euros >= s.alerte_seuil_euros:
            motif = "seuil"
        elif long_retard and euros >= s.alerte_seuil_euros * s.alerte_ratio_seuil_incident:
            motif = "incident"
        else:
            continue
        candidats.append(Candidat(line_id, euros, mv, min(o.quand for o in trains),
                                  max(trains, key=lambda o: (o.mv, o.duree)), motif))
    return sorted(candidats, key=lambda c: -c.euros)


# ── Anti-spam ─────────────────────────────────────────────

def en_silence(maintenant: datetime, s=None) -> bool:
    s = s or get_settings()
    h = maintenant.astimezone(PARIS_TZ).hour
    debut, fin = s.alerte_silence_debut, s.alerte_silence_fin
    return (h >= debut or h < fin) if debut > fin else (debut <= h < fin)


def autorisees(candidats: list[Candidat], envois: list[dict], maintenant: datetime, s=None) -> list[Candidat]:
    """Candidats envoyables maintenant, dans l'ordre, compte tenu des alertes déjà envoyées
    (envois : [{"ligne": line_id, "quand": ISO}])."""
    s = s or get_settings()
    if en_silence(maintenant, s):
        return []
    jour = maintenant.astimezone(PARIS_TZ).date()
    passes = [(e["ligne"], datetime.fromisoformat(e["quand"])) for e in envois]
    restant = s.alerte_max_jour - sum(1 for _, q in passes if q.astimezone(PARIS_TZ).date() == jour)
    retenus = []
    for c in candidats:
        if restant <= 0:
            break
        recent = any(l == c.line_id and maintenant - q < timedelta(hours=s.alerte_delai_ligne_h) for l, q in passes)
        if not recent:
            retenus.append(c)
            restant -= 1
    return retenus


def lire_etat(chemin: Path) -> dict:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"envois": []}
    except Exception:
        logger.exception("État des alertes illisible (%s) : repart de zéro", chemin)
        return {"envois": []}


def noter_envoi(chemin: Path, line_id: str, maintenant: datetime) -> None:
    """Ajoute l'envoi à l'état ; ne garde que les 7 derniers jours. Écriture atomique (fichier temporaire)."""
    etat = lire_etat(chemin)
    limite = maintenant - timedelta(days=7)
    envois = [e for e in etat.get("envois", []) if datetime.fromisoformat(e["quand"]) > limite]
    envois.append({"ligne": line_id, "quand": maintenant.isoformat()})
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps({"envois": envois}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)


# ── Contenu ───────────────────────────────────────────────

def _heure(d: datetime) -> str:
    d = d.astimezone(PARIS_TZ)
    return f"{d.hour}h{d.minute:02d}"


def _accord_cumule(minutes: int) -> str:
    return "cumulées" if minutes < 2 * 1440 else "cumulés"   # minutes/heures, puis jours/ans


def composer_texte(c: Candidat, maintenant: datetime) -> str:
    """Post X : froid, factuel, sans emoji ni lien, ≤ 240 caractères, hashtag de la ligne."""
    tete = (f"{NOMS.get(c.line_id, c.line_id)}, {_heure(maintenant)} : {_fmt(c.euros)} € de temps perdu "
            f"depuis {_heure(c.depuis)}. {_fmt_duree(c.mv)} {_accord_cumule(c.mv)}.")
    p = c.pire
    if p.gare:
        detail = (f" Train supprimé à {p.gare}." if p.supprime
                  else f" Retard de {p.duree} min à {p.gare}.")
    else:
        detail = ""
    queue = " " + hashtag(c.line_id)
    texte = tete + detail + queue
    if len(texte) > LONGUEUR_MAX:          # nom de gare trop long : on retire le détail
        texte = tete + queue
    return texte[:LONGUEUR_MAX]


def lien_x(texte: str) -> str:
    return "https://x.com/intent/post?text=" + quote(texte, safe="")


async def generer_image(c: Candidat, maintenant: datetime, chemin: Path) -> Path | None:
    """frontend/alerte.html rendue par Chromium (même mécanique que bot.generer_carte_png), 1200×675."""
    from playwright.async_api import async_playwright

    m = maintenant.astimezone(PARIS_TZ)
    params = urlencode({
        "ligne": c.line_id, "euros": _fmt(c.euros), "duree": f"{_fmt_duree(c.mv)} {_accord_cumule(c.mv)}",
        "quand": f"{m.day:02d}/{m.month:02d}/{m.year} · {_heure(m)}", "depuis": _heure(c.depuis),
    })
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
            page = await browser.new_page(viewport={"width": 1200, "height": 675})
            await page.goto(f"http://127.0.0.1:8000/alerte.html?{params}", wait_until="domcontentloaded",
                            timeout=30_000)
            await page.wait_for_function("document.body.dataset.pret === '1'", timeout=30_000)
            await page.screenshot(path=str(chemin), type="png")
            await browser.close()
        return chemin
    except Exception:
        logger.exception("Image d'alerte non générée")
        return None


# ── Envoi Telegram ────────────────────────────────────────

async def envoyer_telegram(texte: str, image: Path | None, s=None) -> bool:
    """sendPhoto (sendMessage sans image) : texte dans un bloc code, bouton « Ouvrir dans X ».
    Ne lève jamais : False et un log en cas d'échec."""
    import httpx

    s = s or get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        logger.warning("Alerte non envoyée : TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID absent du .env")
        return False
    donnees = {
        "chat_id": s.telegram_chat_id,
        "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "Ouvrir dans X", "url": lien_x(texte)}]]}),
    }
    legende = f"<code>{html.escape(texte)}</code>"
    url = f"{TELEGRAM_API}/bot{s.telegram_bot_token}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            if image and image.exists():
                with image.open("rb") as f:
                    resp = await http.post(f"{url}/sendPhoto", data={**donnees, "caption": legende},
                                           files={"photo": (image.name, f, "image/png")})
            else:
                resp = await http.post(f"{url}/sendMessage", data={**donnees, "text": legende})
        if resp.status_code != 200:
            # Le corps de la réponse ne contient pas le token (il est dans l'URL, jamais journalisée)
            logger.error("Telegram a refusé l'alerte : HTTP %s %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:
        logger.error("Envoi Telegram impossible : %s", type(exc).__name__)
        return False


# ── Cycle ─────────────────────────────────────────────────

async def _obs_depuis(debut: datetime, fin: datetime, maintenant: datetime) -> list[Obs]:
    """Trains retardés ou supprimés relevés entre debut et fin, comptés comme sur le site."""
    from sqlalchemy import or_, select
    from backend.database import AsyncSessionLocal
    from backend.metrics import incident_minutes_voyageurs
    from backend.models import Incident

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Incident).where(
            Incident.heure_debut > debut, Incident.heure_debut <= fin,
            or_(Incident.source == "realtime", Incident.is_cancelled == True),  # noqa: E712
        ))).scalars().all()
    obs = []
    for inc in rows:
        duree, mv = incident_minutes_voyageurs(inc, maintenant)
        obs.append(Obs(inc.line_id, inc.heure_debut, duree, mv, inc.gare, bool(inc.is_cancelled)))
    return obs


async def verifier_alertes(maintenant: datetime | None = None, dry_run: bool = False,
                           dossier: Path = DOSSIER_ALERTES) -> list[str]:
    """Un tour : évalue, filtre (anti-spam), envoie. Renvoie les textes retenus. Ne lève jamais."""
    try:
        s = get_settings()
        maintenant = maintenant or datetime.now(timezone.utc)
        etat_chemin = dossier / "etat.json"
        if not dry_run and en_silence(maintenant, s):
            return []
        obs = await _obs_depuis(maintenant - timedelta(minutes=s.alerte_fenetre_min), maintenant, maintenant)
        candidats = evaluer(obs, maintenant, s)
        if dry_run:
            # Dry-run : montre la ligne la plus coûteuse même sous le seuil, pour juger le rendu
            retenus = candidats or _meilleure_ligne(obs, maintenant, s)
        else:
            retenus = autorisees(candidats, lire_etat(etat_chemin).get("envois", []), maintenant, s)
        textes = []
        for c in retenus:
            texte = composer_texte(c, maintenant)
            m = maintenant.astimezone(PARIS_TZ)
            image = await generer_image(c, maintenant, dossier / f"{m:%Y-%m-%d-%H%M}-{c.line_id}.png")
            textes.append(texte)
            if dry_run:
                etat = "DÉCLENCHE" if candidats else "sous le seuil"
                print(f"[dry-run · {etat} · {c.motif} · {c.euros} € sur {s.alerte_fenetre_min} min]\n"
                      f"{texte}\n({len(texte)} caractères)\nImage : {image}\nBouton : {lien_x(texte)}\n")
                continue
            if await envoyer_telegram(texte, image, s):
                noter_envoi(etat_chemin, c.line_id, maintenant)
                logger.info("Alerte envoyée (%s, %s €) : %s", c.line_id, c.euros, texte)
        return textes
    except Exception:
        logger.exception("Erreur dans les alertes (collecte non affectée)")
        return []


def _meilleure_ligne(obs: list[Obs], maintenant: datetime, s) -> list[Candidat]:
    """Dry-run sans déclenchement : la ligne la plus coûteuse, pour juger le rendu."""
    return evaluer(obs, maintenant, s.model_copy(update={"alerte_seuil_euros": 0}))[:1]


# ── Backtest ──────────────────────────────────────────────

def rejouer(obs: list[Obs], jours: list[date], s, pas_min: int = 5) -> dict[date, list[Candidat]]:
    """Rejoue relevé par relevé (toutes les pas_min minutes, de la reprise de collecte à minuit) :
    déclencheur + anti-spam, comme en production. Renvoie les alertes envoyées par jour."""
    obs = sorted(obs, key=lambda o: o.quand)
    instants = [o.quand for o in obs]
    envois: list[dict] = []
    resultat: dict[date, list[Candidat]] = {}
    for jour in jours:
        resultat[jour] = []
        t = datetime.combine(jour, time(s.collecte_heure_debut), tzinfo=PARIS_TZ)
        fin = datetime.combine(jour + timedelta(days=1), time(0), tzinfo=PARIS_TZ)
        while t < fin:
            tu = t.astimezone(timezone.utc)
            i = bisect.bisect_right(instants, tu - timedelta(minutes=s.alerte_fenetre_min))
            j = bisect.bisect_right(instants, tu)
            for c in autorisees(evaluer(obs[i:j], tu, s), envois, tu, s):
                envois.append({"ligne": c.line_id, "quand": tu.isoformat()})
                resultat[jour].append(c)
            t += timedelta(minutes=pas_min)
    return resultat


async def backtest(nb_jours: int, seuils: list[int] | None = None) -> None:
    s = get_settings()
    aujourdhui = datetime.now(PARIS_TZ).date()
    jours = [aujourdhui - timedelta(days=k) for k in range(nb_jours, 0, -1)]   # jours complets, pas aujourd'hui
    debut = datetime.combine(jours[0], time(0), tzinfo=PARIS_TZ).astimezone(timezone.utc)
    fin = datetime.combine(aujourdhui, time(0), tzinfo=PARIS_TZ).astimezone(timezone.utc)
    obs = await _obs_depuis(debut - timedelta(hours=2), fin, datetime.now(timezone.utc))
    print(f"{len(obs)} trains retardés ou supprimés du {jours[0]} au {jours[-1]}\n")

    detail = rejouer(obs, jours, s)
    print(f"Seuils actuels : {s.alerte_seuil_euros} € sur {s.alerte_fenetre_min} min "
          f"(ou train ≥ {s.alerte_duree_incident_min} min et ≥ {int(s.alerte_seuil_euros * s.alerte_ratio_seuil_incident)} €)")
    for jour, alertes in detail.items():
        lignes = ", ".join(f"{NOMS.get(c.line_id)} {_fmt(c.euros)} € ({c.motif})" for c in alertes)
        print(f"  {jour:%a %d/%m} : {len(alertes)}  {lignes}")
    total = sum(len(a) for a in detail.values())
    print(f"  Total : {total} en {nb_jours} jours, soit {total * 7 / nb_jours:.1f} par semaine\n")

    seuils = seuils or list(range(2000, 30001, 1000))
    print("Seuil (€)  alertes/semaine")
    proposes = []
    for seuil in seuils:
        essai = s.model_copy(update={"alerte_seuil_euros": seuil})
        n = sum(len(a) for a in rejouer(obs, jours, essai).values()) * 7 / nb_jours
        print(f"  {seuil:>6}   {n:5.1f}")
        if 3 <= n <= 5:
            proposes.append(seuil)
    if proposes:
        print(f"\nSEUIL_EUROS proposé (3 à 5 alertes par semaine) : {proposes[len(proposes) // 2]} € "
              f"(plage {proposes[0]}–{proposes[-1]} €)")
    else:
        print("\nAucun seuil testé ne donne 3 à 5 alertes par semaine : élargir la plage (--seuils).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("commande", nargs="?", choices=["backtest"], help="backtest sur l'historique")
    parser.add_argument("--dry-run", action="store_true", help="évalue maintenant, affiche, n'envoie rien")
    parser.add_argument("--jours", type=int, default=14)
    parser.add_argument("--seuils", type=lambda v: [int(x) for x in v.split(",")], default=None,
                        help="seuils à tester, ex. 3000,5000,8000")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.commande == "backtest":
        asyncio.run(backtest(args.jours, args.seuils))
    elif args.dry_run:
        asyncio.run(verifier_alertes(dry_run=True, dossier=DOSSIER_ALERTES / "dry-run"))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
