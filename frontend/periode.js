// periode.js — Période affichée par carte.html et carousel.html.
// Sans paramètre : le jour (/api/stats/today). Bilans du dimanche (bot.py) :
// ?type=semaine|mois&du=AAAA-MM-JJ&au=AAAA-MM-JJ → /api/stats/periode, même forme de données.
const PERIODE = (() => {
  const q = new URLSearchParams(location.search);
  const type = q.get('type'), du = q.get('du'), au = q.get('au');
  const MOIS = ['janvier','février','mars','avril','mai','juin','juillet','août',
                'septembre','octobre','novembre','décembre'];
  const jour = iso => new Date(iso + 'T12:00:00');
  if ((type === 'semaine' || type === 'mois') && du && au) {
    const d1 = jour(du), d2 = jour(au), mois = MOIS[d2.getMonth()];
    return {
      type, du, au,
      quand: type === 'semaine' ? 'Cette semaine' : 'En ' + mois,          // début de phrase
      pendant: type === 'semaine' ? 'cette semaine' : 'en ' + mois,        // fin de phrase
      libelle: type === 'semaine'
        ? `Semaine du ${d1.getDate()}${d1.getMonth() !== d2.getMonth() ? ' ' + MOIS[d1.getMonth()] : ''}`
          + ` au ${d2.getDate()} ${mois} ${d2.getFullYear()}`
        : `${mois.charAt(0).toUpperCase() + mois.slice(1)} ${d2.getFullYear()} · du 1er au ${d2.getDate()}`,
    };
  }
  return { type: 'jour', quand: 'Aujourd’hui', pendant: 'aujourd’hui', libelle: null };
})();

// { today, lines } : today = totaux (cout_eur, total_minutes_voyageurs, total_incidents, nb_lignes_perturbees,
// date), lines = détail par ligne (line_id, minutes_voyageurs, nb_cancelled, nb_rt_delays, trains_prevus…)
async function chargerDonnees() {
  if (PERIODE.type !== 'jour') {
    const p = await (await fetch(`/api/stats/periode?du=${PERIODE.du}&au=${PERIODE.au}`)).json();
    return { today: { ...p, date: p.au }, lines: p.lignes };
  }
  const [today, lines] = await Promise.all([
    fetch('/api/stats/today').then(r => r.json()),
    fetch('/api/stats/today/lines').then(r => r.json()),
  ]);
  return { today, lines };
}

// Date affichée en tête : le jour (« mardi 3 novembre 2026 ») ou la période
function libellePeriode(today) {
  return PERIODE.libelle || new Date(today.date + 'T12:00:00').toLocaleDateString('fr-FR',
    {weekday:'long', day:'numeric', month:'long', year:'numeric'});
}
