"""
causes.py — Classement des motifs déclarés par l'opérateur en catégories de causes.

Les motifs viennent du texte libre des perturbations PRIM (Incident.cause, source = 'disruption'),
souvent en HTML avec entités. Les retards temps réel n'ont pas de motif et ne passent pas par ici.
"""
import html
import re
import unicodedata

CATEGORIES: tuple[str, ...] = (
    "Signalisation / infrastructure",
    "Panne matériel",
    "Incident voyageur",
    "Mouvement social",
    "Météo",
    "Travaux",
    "Non précisé",
)

NON_PRECISE = "Non précisé"
TRAVAUX = "Travaux"

# Ordre de priorité : première catégorie reconnue gagnante.
# Pas de « voyageur » seul : il apparaît dans les formules types des messages de travaux
# (« les voyageurs sont invités à… »).
_MOTS_CLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Mouvement social", ("greve", "mouvement social", "preavis")),
    ("Incident voyageur", (
        "malaise", "accident de personne", "personne sur les voies", "incident voyageur",
        "voyageur malade", "colis suspect", "bagage", "objet abandonne", "intrusion", "heurt",
        "signal d'alarme",
    )),
    ("Signalisation / infrastructure", (
        "signalisation", "aiguillage", "catenaire", "alimentation electrique", "panne electrique",
        "infrastructure", "rupture de rail", "passage a niveau", "affectant la voie",
        "incident sur la voie", "objet sur la voie", "installations",
    )),
    ("Panne matériel", (
        "train en panne", "panne d'un train", "panne de train", "materiel roulant",
        "incident technique sur un train", "avarie", "panne materiel",
    )),
    ("Météo", (
        "intemperie", "neige", "verglas", "tempete", "orage", "chute d'arbre", "vegetation",
        "canicule", "inondation", "vent violent",
    )),
    (TRAVAUX, ("travaux", "chantier", "maintenance", "modernisation")),
)

# Avis planifié (période, dates, plage de jours) : des travaux, même si le texte cite ensuite
# la signalisation ou les installations concernées.
_PLANIFIE: tuple[re.Pattern, ...] = (
    re.compile(r"periode\s*:"),
    re.compile(r"dates?\s*:"),
    re.compile(r"\bdu\s+\d{1,2}/\d{1,2}"),                             # « du 31/08 »
    re.compile(r"\b\d{1,2}(?:/\d{1,2})?\s*[-–]\s*\d{1,2}/\d{1,2}\b"),  # « 7 - 11/09 », « 7/09 - 11/12 »
)

# Motif explicite de l'opérateur : « … Motif : malaise voyageur dans un train (incident terminé). »
_MOTIF_DECLARE = re.compile(r"\bmotif\s*:\s*(.+)")

# Vraies balises uniquement : « Combs-la-Ville <-> Melun » doit garder sa flèche
_BALISE = re.compile(r"</?[a-zA-Z][^>]*>")
_SAUT = re.compile(r"<\s*/?\s*(?:br|p|div|li)\b[^>]*>", re.IGNORECASE)

# Lignes d'en-tête ou de service des messages PRIM, sautées pour le résumé
_ENTETE = re.compile(
    r"^(?:periode|dates?|motif|pour plus d'informations|itineraires? recommandes?|"
    r"les horaires du calculateur|-)"
)


def texte_lisible(texte: str | None) -> str:
    """HTML PRIM → texte affichable : entités décodées, balises retirées, une ligne par paragraphe."""
    if not texte:
        return ""
    t = _SAUT.sub("\n", texte)
    t = _BALISE.sub(" ", t)
    t = html.unescape(t)
    lignes = (re.sub(r"\s+", " ", l).strip() for l in t.split("\n"))
    return "\n".join(l for l in lignes if l)


def resume_perturbation(texte: str | None) -> str:
    """Première ligne informative : saute « Période : », « Dates : », « Motif : », renvois et listes."""
    lignes = texte_lisible(texte).split("\n")
    for ligne in lignes:
        if not _ENTETE.match(normaliser(ligne)):
            return ligne
    return lignes[0]


def normaliser(texte: str | None) -> str:
    """HTML → texte brut, sans accents, en minuscules, espaces réduits."""
    if not texte:
        return ""
    t = _BALISE.sub(" ", texte)
    t = html.unescape(t)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("’", "'").lower()
    return re.sub(r"\s+", " ", t).strip()


def _par_mots_cles(t: str) -> str:
    for categorie, mots in _MOTS_CLES:
        if any(m in t for m in mots):
            return categorie
    return NON_PRECISE


def categoriser_cause(texte: str | None) -> str:
    """Motif déclaré (« Motif : … ») d'abord, puis avis planifié → travaux, puis mots-clés."""
    t = normaliser(texte)
    if not t:
        return NON_PRECISE
    motif = _MOTIF_DECLARE.search(t)
    if motif:
        # Tête du motif d'abord : « travaux sur le réseau ferroviaire (… de signalisation …) » = travaux
        tete = re.split(r"[(.]", motif.group(1), maxsplit=1)[0]
        for segment in (tete, motif.group(1)):
            categorie = _par_mots_cles(segment)
            if categorie != NON_PRECISE:
                return categorie
    if any(r.search(t) for r in _PLANIFIE):
        return TRAVAUX
    return _par_mots_cles(t)
