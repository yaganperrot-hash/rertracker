"""
share.py — Génération d'images de partage (cartes sociales) via Pillow.

3 formats : square (1080x1080), story (1080x1920), og (1200x630).
"""
import io
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from backend.config import get_settings

PARIS_TZ = ZoneInfo("Europe/Paris")

# ── Polices ──
_FONTS_DIR = Path(__file__).parent / "fonts"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONTS_DIR / name), size)


# ── Couleurs et métadonnées de lignes (miroir de LINE_META frontend) ──
LINE_COLORS: dict[str, dict] = {
    "RER_A":        {"short": "A", "name": "RER A",        "color": "#E2231A", "textColor": "#FFFFFF"},
    "RER_B":        {"short": "B", "name": "RER B",        "color": "#5191CF", "textColor": "#FFFFFF"},
    "RER_C":        {"short": "C", "name": "RER C",        "color": "#C8A800", "textColor": "#1A1916"},
    "RER_D":        {"short": "D", "name": "RER D",        "color": "#00814F", "textColor": "#FFFFFF"},
    "RER_E":        {"short": "E", "name": "RER E",        "color": "#B04191", "textColor": "#FFFFFF"},
    "TRANSILIEN_H": {"short": "H", "name": "Transilien H", "color": "#7B7B7B", "textColor": "#FFFFFF"},
    "TRANSILIEN_J": {"short": "J", "name": "Transilien J", "color": "#D2B464", "textColor": "#1A1916"},
    "TRANSILIEN_K": {"short": "K", "name": "Transilien K", "color": "#8C4B31", "textColor": "#1A1916"},
    "TRANSILIEN_L": {"short": "L", "name": "Transilien L", "color": "#9F3E96", "textColor": "#FFFFFF"},
    "TRANSILIEN_N": {"short": "N", "name": "Transilien N", "color": "#333333", "textColor": "#FFFFFF"},
    "TRANSILIEN_P": {"short": "P", "name": "Transilien P", "color": "#E87722", "textColor": "#1A1916"},
    "TRANSILIEN_R": {"short": "R", "name": "Transilien R", "color": "#228B22", "textColor": "#1A1916"},
    "TRANSILIEN_U": {"short": "U", "name": "Transilien U", "color": "#7B0F1F", "textColor": "#FFFFFF"},
}

# ── Charte graphique ──
BG = "#F7F4EF"
INK = "#000000"
SUB = "#333333"
MUTED = "#555555"
RED = "#C0392B"

# ── Formatage (miroir de bot.py) ──
_NNBS = "\u202f"


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", _NNBS)


def _fmt_euros_compact(n: int) -> str:
    """142681 → '142 681 €', 1204567 → '1,2 M€'"""
    if n >= 1_000_000:
        m = n / 1_000_000
        if m >= 10:
            return f"{_fmt(round(m))}{_NNBS}M€"
        return f"{m:.1f}{_NNBS}M€".replace(".", ",")
    return f"{_fmt(n)}{_NNBS}€"


def _jours_smic_label(jours: int) -> str:
    """Jours de travail au SMIC → texte lisible."""
    if jours < 365:
        return f"{_fmt(jours)} jours"
    mois = round(jours / 30.44)
    if mois < 24:
        return f"{mois} mois"
    ans = jours / 365.25
    a = int(ans)
    m = round((ans - a) * 12)
    if m == 0:
        return f"{a} ans"
    return f"{a} ans {m} mois"


def _classement_label(rang: int, total: int) -> str:
    suf = "ʳᵉ" if rang == 1 else "ᵉ"
    return f"{rang}{suf} pire ligne / {total}"


def _accroche(line_id: str) -> str:
    meta = LINE_COLORS.get(line_id, {})
    name = meta.get("name", line_id)
    if line_id.startswith("RER_"):
        return f"le {name}"
    return f"la {name}"


# ── Jours FR ──
_JOURS = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE"]
_MOIS = ["", "JANV.", "FÉVR.", "MARS", "AVR.", "MAI", "JUIN",
         "JUIL.", "AOÛT", "SEPT.", "OCT.", "NOV.", "DÉC."]


def _date_label(d: date) -> str:
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month]} {d.year}"


# ── Données pour une carte ──

def compute_card_data(line_id: str, target_date: date,
                      daily_metrics: list[dict]) -> dict:
    """Calcule les données nécessaires au rendu d'une carte.

    daily_metrics : liste de dicts {line_id, minutes_voyageurs, cout_eur} pour toutes les lignes à cette date.
    """
    smic = get_settings().smic_horaire

    my = next((m for m in daily_metrics if m["line_id"] == line_id), None)
    cout = my["cout_eur"] if my else 0
    mv = my["minutes_voyageurs"] if my else 0

    # Jours de travail au SMIC (7h/jour)
    jours_smic = math.floor(cout / (smic * 7)) if cout > 0 else 0

    # Classement (par coût décroissant)
    sorted_lines = sorted(daily_metrics, key=lambda x: x["cout_eur"], reverse=True)
    rang = next((i + 1 for i, x in enumerate(sorted_lines) if x["line_id"] == line_id), None)
    total_lignes = len(sorted_lines) if sorted_lines else len(LINE_COLORS)

    return {
        "line_id": line_id,
        "date": target_date,
        "cout_eur": cout,
        "minutes_voyageurs": mv,
        "jours_smic": jours_smic,
        "rang": rang,
        "total_lignes": total_lignes,
    }


# ── Helpers de dessin ──

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _draw_circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill: str):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def _draw_text_centered(draw: ImageDraw.ImageDraw, x: int, y: int,
                        text: str, font: ImageFont.FreeTypeFont, fill: str):
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x - tw // 2, y - th // 2), text, fill=fill, font=font)


def _auto_size_text(draw: ImageDraw.ImageDraw, text: str, font_name: str,
                    max_size: int, min_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    """Réduit la taille de police jusqu'à ce que le texte tienne dans max_width."""
    for size in range(max_size, min_size - 1, -2):
        font = _font(font_name, size)
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return _font(font_name, min_size)


# ── Layouts ──

def _draw_square(img: Image.Image, draw: ImageDraw.ImageDraw, data: dict):
    """Layout carré 1080×1080 — bande couleur en haut."""
    W, H = 1080, 1080
    meta = LINE_COLORS[data["line_id"]]
    color = meta["color"]
    text_color = meta["textColor"]
    PAD = 72

    # Bande couleur en haut (80px)
    draw.rectangle([0, 0, W, 80], fill=color)

    # Pastille ronde (centrée, sous la bande)
    circle_y = 180
    circle_r = 52
    _draw_circle(draw, W // 2, circle_y, circle_r, color)
    letter_font = _font("Roboto-Black.ttf", 48)
    _draw_text_centered(draw, W // 2, circle_y, meta["short"], letter_font, text_color)

    # Date en petites capitales
    date_font = _font("Roboto-Bold.ttf", 22)
    date_text = _date_label(data["date"])
    _draw_text_centered(draw, W // 2, 270, date_text, date_font, MUTED)

    if data["cout_eur"] == 0:
        # Cas 0 €
        msg_font = _font("Roboto-Bold.ttf", 36)
        _draw_text_centered(draw, W // 2, 420, f"Aucun retard sur", msg_font, INK)
        _draw_text_centered(draw, W // 2, 470, f"{_accroche(data['line_id'])}", msg_font, INK)
        msg2_font = _font("Roboto-Regular.ttf", 28)
        _draw_text_centered(draw, W // 2, 540, "pour l'instant.", msg2_font, MUTED)
    else:
        # Accroche
        accroche_font = _font("Roboto-Regular.ttf", 30)
        accroche = f"Aujourd'hui, {_accroche(data['line_id'])} nous a coûté"
        _draw_text_centered(draw, W // 2, 330, accroche, accroche_font, SUB)

        # Montant (auto-sized)
        cout_text = f"{_fmt(data['cout_eur'])} €"
        cout_font = _auto_size_text(draw, cout_text, "Roboto-Black.ttf", 120, 60, W - PAD * 2)
        _draw_text_centered(draw, W // 2, 440, cout_text, cout_font, INK)

        # Filet
        draw.line([(PAD + 100, 520), (W - PAD - 100, 520)], fill=MUTED, width=2)

        # Jours SMIC en rouge
        if data["jours_smic"] > 0:
            smic_font = _font("Roboto-Bold.ttf", 30)
            smic_text = f"soit {_jours_smic_label(data['jours_smic'])} de travail au SMIC"
            _draw_text_centered(draw, W // 2, 570, smic_text, smic_font, RED)

        # Classement
        if data["rang"]:
            rank_font = _font("Roboto-Regular.ttf", 26)
            rank_text = _classement_label(data["rang"], data["total_lignes"])
            _draw_text_centered(draw, W // 2, 640, rank_text, rank_font, MUTED)

    # Footer
    foot_y = H - 80
    draw.line([(PAD, foot_y - 20), (W - PAD, foot_y - 20)], fill=MUTED, width=1)
    sig_font = _font("Roboto-Bold.ttf", 20)
    sig_text = "IDF-RETARD · idf-retard.fr"
    _draw_text_centered(draw, W // 2, foot_y + 10, sig_text, sig_font, MUTED)


def _draw_story(img: Image.Image, draw: ImageDraw.ImageDraw, data: dict):
    """Layout story 1080×1920 — même structure, typo plus grande."""
    W, H = 1080, 1920
    meta = LINE_COLORS[data["line_id"]]
    color = meta["color"]
    text_color = meta["textColor"]
    PAD = 72

    # Bande couleur en haut (100px)
    draw.rectangle([0, 0, W, 100], fill=color)

    # Pastille ronde
    circle_y = 260
    circle_r = 64
    _draw_circle(draw, W // 2, circle_y, circle_r, color)
    letter_font = _font("Roboto-Black.ttf", 58)
    _draw_text_centered(draw, W // 2, circle_y, meta["short"], letter_font, text_color)

    # Date
    date_font = _font("Roboto-Bold.ttf", 28)
    date_text = _date_label(data["date"])
    _draw_text_centered(draw, W // 2, 380, date_text, date_font, MUTED)

    if data["cout_eur"] == 0:
        msg_font = _font("Roboto-Bold.ttf", 44)
        _draw_text_centered(draw, W // 2, 650, f"Aucun retard sur", msg_font, INK)
        _draw_text_centered(draw, W // 2, 710, f"{_accroche(data['line_id'])}", msg_font, INK)
        msg2_font = _font("Roboto-Regular.ttf", 34)
        _draw_text_centered(draw, W // 2, 800, "pour l'instant.", msg2_font, MUTED)
    else:
        # Accroche
        accroche_font = _font("Roboto-Regular.ttf", 38)
        accroche = f"Aujourd'hui, {_accroche(data['line_id'])} nous a coûté"
        _draw_text_centered(draw, W // 2, 480, accroche, accroche_font, SUB)

        # Montant
        cout_text = f"{_fmt(data['cout_eur'])} €"
        cout_font = _auto_size_text(draw, cout_text, "Roboto-Black.ttf", 150, 70, W - PAD * 2)
        _draw_text_centered(draw, W // 2, 650, cout_text, cout_font, INK)

        # Filet
        draw.line([(PAD + 100, 770), (W - PAD - 100, 770)], fill=MUTED, width=2)

        # Jours SMIC
        if data["jours_smic"] > 0:
            smic_font = _font("Roboto-Bold.ttf", 36)
            smic_text = f"soit {_jours_smic_label(data['jours_smic'])} de travail au SMIC"
            _draw_text_centered(draw, W // 2, 840, smic_text, smic_font, RED)

        # Classement
        if data["rang"]:
            rank_font = _font("Roboto-Regular.ttf", 32)
            rank_text = _classement_label(data["rang"], data["total_lignes"])
            _draw_text_centered(draw, W // 2, 930, rank_text, rank_font, MUTED)

    # Footer
    foot_y = H - 100
    draw.line([(PAD, foot_y - 20), (W - PAD, foot_y - 20)], fill=MUTED, width=1)
    sig_font = _font("Roboto-Bold.ttf", 24)
    sig_text = "IDF-RETARD · idf-retard.fr"
    _draw_text_centered(draw, W // 2, foot_y + 14, sig_text, sig_font, MUTED)


def _draw_landscape(img: Image.Image, draw: ImageDraw.ImageDraw, data: dict):
    """Layout paysage 1200×630 (og:image) — bande couleur à gauche."""
    W, H = 1200, 630
    meta = LINE_COLORS[data["line_id"]]
    color = meta["color"]
    text_color = meta["textColor"]

    # Bande couleur à gauche (60px)
    draw.rectangle([0, 0, 60, H], fill=color)

    # Pastille ronde (à gauche du contenu)
    circle_x = 160
    circle_y = H // 2 - 40
    circle_r = 48
    _draw_circle(draw, circle_x, circle_y, circle_r, color)
    letter_font = _font("Roboto-Black.ttf", 44)
    _draw_text_centered(draw, circle_x, circle_y, meta["short"], letter_font, text_color)

    # Contenu à droite de la pastille
    left = 240
    right = W - 60

    # Date
    date_font = _font("Roboto-Bold.ttf", 18)
    date_text = _date_label(data["date"])
    draw.text((left, 60), date_text, fill=MUTED, font=date_font)

    if data["cout_eur"] == 0:
        msg_font = _font("Roboto-Bold.ttf", 32)
        draw.text((left, 180), f"Aucun retard sur {_accroche(data['line_id'])}", fill=INK, font=msg_font)
        msg2_font = _font("Roboto-Regular.ttf", 26)
        draw.text((left, 230), "pour l'instant.", fill=MUTED, font=msg2_font)
    else:
        # Accroche
        accroche_font = _font("Roboto-Regular.ttf", 24)
        accroche = f"Aujourd'hui, {_accroche(data['line_id'])} nous a coûté"
        draw.text((left, 110), accroche, fill=SUB, font=accroche_font)

        # Montant
        cout_text = f"{_fmt(data['cout_eur'])} €"
        cout_font = _auto_size_text(draw, cout_text, "Roboto-Black.ttf", 90, 50, right - left)
        draw.text((left, 160), cout_text, fill=INK, font=cout_font)

        # Filet
        draw.line([(left, 290), (right - 40, 290)], fill=MUTED, width=2)

        # Jours SMIC
        if data["jours_smic"] > 0:
            smic_font = _font("Roboto-Bold.ttf", 24)
            smic_text = f"soit {_jours_smic_label(data['jours_smic'])} de travail au SMIC"
            draw.text((left, 315), smic_text, fill=RED, font=smic_font)

        # Classement
        if data["rang"]:
            rank_font = _font("Roboto-Regular.ttf", 22)
            rank_text = _classement_label(data["rang"], data["total_lignes"])
            draw.text((left, 365), rank_text, fill=MUTED, font=rank_font)

    # Nom de ligne (centré sous la pastille)
    name_font = _font("Roboto-Bold.ttf", 20)
    _draw_text_centered(draw, circle_x, circle_y + circle_r + 30, meta["name"], name_font, INK)

    # Signature en bas à droite
    sig_font = _font("Roboto-Bold.ttf", 16)
    sig_text = "IDF-RETARD · idf-retard.fr"
    bbox = sig_font.getbbox(sig_text)
    tw = bbox[2] - bbox[0]
    draw.text((right - tw, H - 50), sig_text, fill=MUTED, font=sig_font)


# ── Point d'entrée ──

FORMATS = {
    "square": (1080, 1080, _draw_square),
    "story":  (1080, 1920, _draw_story),
    "og":     (1200, 630,  _draw_landscape),
}


def render_card(data: dict, fmt: str = "square") -> bytes:
    """Génère une carte PNG pour les réseaux sociaux.

    data : dict retourné par compute_card_data()
    fmt  : 'square', 'story' ou 'og'
    Retourne les bytes PNG.
    """
    if fmt not in FORMATS:
        fmt = "square"
    w, h, draw_fn = FORMATS[fmt]

    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw_fn(img, draw, data)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def effective_date() -> date:
    """Date effective pour la carte : avant 6 h Paris → veille."""
    now = datetime.now(PARIS_TZ)
    heure_debut = get_settings().collecte_heure_debut
    if now.hour < heure_debut:
        return (now - timedelta(days=1)).date()
    return now.date()
