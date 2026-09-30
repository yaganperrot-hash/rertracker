# Leçons apprises

## Pièges Python / FastAPI
- `pydantic-settings` est un package séparé depuis Pydantic v2 — `BaseSettings` n'est plus dans `pydantic`. Toujours l'ajouter à `requirements.txt`.
- `DATABASE_URL` avec préfixe `postgresql://` ne fonctionne pas avec asyncpg — convertir en `postgresql+asyncpg://` au runtime dans `database.py`.

## Pastilles / badges de ligne
- Ne jamais utiliser `grid-template-columns: repeat(N, 1fr)` pour des cercles : les colonnes `1fr` étirent les éléments. Utiliser `display:flex; flex-wrap:wrap` avec `flex:none` sur chaque pastille.
- Taille fixe en px par contexte (grille: 88px, en-tête panneau: 40px, tableau: 28px). Font = ~0.42 × diamètre.
- Centrage par flexbox uniquement (`display:flex; align-items:center; justify-content:center; line-height:1`). Jamais de padding ou line-height pour centrer.
- Contraste : fonds clairs (RER C, Transilien J/K/P/R) → texte `#1A1916` via `data-tc="dark"`.

## LINE_META dupliqué
- `LINE_META` est copié dans 3 fichiers (`index.html`, `temps-reel.html`, `ligne.html`). Toute modification (ex: ajout `textColor`) doit être propagée aux 3. Piste future : factoriser dans un fichier partagé.

## Picker
- Le composant `Pick` (pick.js + pick.css) est partagé entre `/` et `/:slug`. Les onglets réseau ont été remplacés par des groupes toujours visibles — plus simple et plus scannable.

## Bilans / JSON statiques
- Le pattern `_ecrire()` (écriture atomique .tmp → rename) est réutilisable pour tout nouveau JSON statique.
- Toujours appeler `generer_bilans()` manuellement après ajout d'un nouveau fichier JSON, sinon la page affiche "Bilan en cours de calcul" jusqu'au prochain cycle scheduler.
- Les données `hall-of-shame.json` contiennent les 3 périodes (semaine/mois/année) dans un seul fichier — le frontend filtre côté client.

## Cohérence cross-pages
- Les styles hero/cumul sont dupliqués dans chaque HTML (pas de CSS partagé). Toute modification de taille/couleur doit être propagée sur les 5 pages : `index.html`, `temps-reel.html`, `statistiques.html`, `ligne.html`, `methode.html`.
- Valeurs de référence (accueil) : compteur `clamp(52px, 10.4vw, 112px)` 900, cumul `clamp(24px, 4vw, 35px)` 700 red, subtitle `clamp(16px, 2.4vw, 22px)` 500, labels 10-11px.
- Le ticker CSS est dupliqué dans chaque page, le JS partagé (`ticker.js`). Chaque page doit appeler
  `Ticker.charger()` (ou `Ticker.render()`), sinon le bandeau reste sur « Chargement… ». Vitesse constante
  `VITESSE_PX_S = 45` : une durée CSS fixe fait défiler un texte long beaucoup trop vite.
- Pour déborder un élément hors de son conteneur max-width : `margin-inline: calc(-50vw + 50%)`.

## APScheduler — race conditions
- Ne jamais lancer en parallèle des jobs qui ont une dépendance séquentielle (ex: collecte → métriques). Utiliser un seul job qui enchaîne les étapes, ou `await` séquentiel au démarrage.
- `next_run_time=datetime.now()` sur plusieurs jobs = exécution simultanée = race condition garantie.
- Pour les métriques quotidiennes avec fenêtre 07h-07h : prévoir un recalcul de la veille au démarrage ET un cron à 07h05 pour finaliser.

## Travail sur deux PC
- Chaque PC a **sa propre base PostgreSQL** : seul git est partagé. Un compteur à 0 sur un PC alors que l'autre affiche des chiffres n'est pas une perte de données — demander d'abord sur quel PC les chiffres ont été vus.
- En début de session : `git fetch` + `git pull --ff-only`. Les `publications/*.txt` générés localement entrent en conflit avec ceux du distant → garder la version du PC dont la base est la plus complète.
- Le `.env` n'est pas versionné : quand un défaut change dans `config.py` (ex. polling 5 → 15 min), vérifier que le `.env` de chaque PC ne l'écrase pas.
- Changer de PC en cours de journée : `python -m backend.transfert export` (serveur arrêté), commit + push, puis `import` sur l'autre PC avant de lancer son serveur. Les ids (`rt_{train}_{AAAAMMJJ}`, id de disruption PRIM) sont identiques d'un PC à l'autre, donc la fusion ne crée pas de doublon.

## Métriques "par usager" — piège de la dilution
- Diviser `minutes_voyageurs` par la fréquentation totale du jour donne un chiffre minuscule : on répartit le retard sur TOUS les voyageurs, y compris les 99% non impactés.
- Diviser le coût total collectif par le nombre d'incidents n'a pas de sens non plus : c'est un coût agrégé de milliers de voyageurs.
- La bonne formule pour "retard moyen vécu par un usager retardé" : `Σ(durée_i × poids_horaire_i) / Σ(poids_horaire_i)` — moyenne des durées pondérée par le flux de voyageurs à l'heure de l'incident.
- Ce calcul nécessite de requêter les incidents individuels (pas les DailyMetric agrégés), mais reste performant même sur 782 incidents.

## Tester une opération sur la base sans risque
- Copie jetable : `createdb X && pg_dump -t incidents -t daily_metrics retards_idf | psql -d X`, puis lancer le script avec `DATABASE_URL=postgresql://…/X` (la variable d'environnement prime sur `.env`). Attention : `generer_bilans()` écrit dans `frontend/data/` quelle que soit la base → régénérer depuis la vraie base après le test.
- Un réimport de ses propres données doit laisser la base strictement identique (même `count`, même `sum`, mêmes totaux du jour) : bon test d'idempotence.

## PRIM / Navitia
- `line_reports` global (sans filtre) répond 200 avec 0 résultat ; `physical_modes/physical_mode:RapidTransit` (5 RER)
  et `physical_mode:LocalTrain` (8 Transilien) renvoient tout, en 1 appel chacun.
- Une interruption (`NO_SERVICE`) ne liste que la ligne dans `impacted_objects` : ni gares, ni tronçon, ni trains —
  le tronçon n'existe qu'en texte libre. Inexploitable pour chiffrer une coupure.
- La plupart des perturbations d'une ligne sont des pannes d'ascenseur en `SIGNIFICANT_DELAYS` valables 1 an :
  l'effet PRIM ne mesure rien, d'où le filtre > 12 h.
- `data_freshness` d'un départ : `base_schedule` sur une ligne de bus (pas de temps réel) — un ID qui ne remonte
  jamais de retard est d'abord un ID à vérifier.
- « Ça tenait les autres jours » : vérifier le rythme réel en base (relevés distincts par heure) avant de le croire —
  les 13 et 14/09 tournaient à 15 min, pas à 5.
- Pendant une interruption, les trains du tronçon coupé disparaissent des départs `realtime` ; le détail par arrêt
  (`deleted`, `no_boarding`) n'existe que via `/vehicle_journeys/{id}`, pas dans `line_reports`.

## Migration de données + transferts entre PC
- Un script qui corrige des étiquettes en base doit être lancé entre les imports : d'abord les exports faits
  avant le correctif, puis le script, puis ceux faits après. Sinon les données déjà justes sont « corrigées » à tort.
- Table témoin (`migrations_appliquees`) + sauvegarde `CREATE TABLE … AS SELECT` : migration rejouable sans risque.
- La table témoin bloque seulement une 2ᵉ exécution du script : un import automatique (`/start`) d'anciens exports
  dans une base déjà corrigée réintroduit les mauvaises étiquettes. Donner au script un `--statut` en lecture seule
  (`to_regclass` : ne crée pas la table) et faire décider l'ordre des imports par ce statut.
- Un ancien fichier encore versionné dans un autre encodage (le 13/09 en cp1252) : lecture UTF-8 avec repli annoncé
  plutôt que conversion du fichier.

## Audit méthodologique (2026-09-26)
- La méthode officielle IDFM/Transilien est binaire (< 5 min = à l'heure), basée sur une matrice OD construite par
  enquêtes terrain tous les 4 ans + comptages. Notre méthode mesure l'ampleur (minutes-voyageurs continues, seuil 2 min),
  utilise les montées open data comme proxy OD (hypothèse : descentes ∝ montées), et valorise au SMIC (12,31 €/h).
- Écart estimé : ±20 % sur les minutes-voyageurs (proxy OD = ±15 %, montées ±10 %, couverture ±7 %).
- Sur le coût € : −25 à −35 % vs référence DGITM (valeur du temps IdF ~15-16 €/h, Quinet 2013 + IGEDD −15 %).
  Le SMIC est dans la fourchette basse → conservateur.
- Avantages de notre méthode vs officielle : granularité arrêt par arrêt (vs terminus), temps réel 5 min (vs journalier),
  gain à quai modélisé, pas de neutralisation (grèves comptées).
- Faiblesse principale : pas de matrice OD réelle (non publique). Les grandes gares-hubs (Châtelet, GdN) sont surestimées
  en destination car elles ont aussi de fortes montées.

## Exploitation
- Jamais de `git stash` (ni de checkout) pendant qu'un serveur démarre en parallèle : il peut importer l'ancien code.
- Une page qui décrit le calcul (Méthode) dérive du code : servir chaque paramètre par `/api/reference` et tester
  que les valeurs servies sont celles du code.
- Un état horodaté (dernier relevé, quota restant) se relit dans les logs à chaque question, avec `date` : un chiffre
  donné une heure plus tôt paraît être une panne de collecte alors qu'il est seulement périmé.

## Open data IDF Mobilités et Éducation nationale (2026-09-16)
- Les validations du réseau ferré sont publiées **par arrêt et par réseau**, jamais par ligne.
  `code_stif_res` regroupe le Transilien par gare parisienne : 852 = N + U (Montparnasse),
  853 = H + K (Paris-Nord), 854 = J + L (Saint-Lazare). Les cinq RER ont chacun leur code (801→805).
  Vérifier un regroupement sur des gares discriminantes (La Verrière, Meaux, Montereau) avant de s'y fier.
- Agréger des profils de gare en profil de ligne demande de **pondérer par le volume de chaque gare** :
  la moyenne simple écrase le résultat vers les petites gares de grande banlieue, au pic plus creusé.
- ODS ne sait pas caster un champ texte en nombre (`sum(int(x))` rejeté) : exporter et sommer côté Python.
- `/records` plafonne à 100 par page ; `/exports/json` rend tout d'un coup, filtre `where` compris.
- Calendrier scolaire (`fr-en-calendrier-scolaire`) : les bornes sont en **UTC à 22 h**, soit minuit
  heure de Paris le lendemain — sans conversion chaque période glisse d'un jour. La borne haute est
  le jour de **rentrée**, donc exclue. Filtrer `population != "Enseignants"`.

## Logique de calcul
- Un profil de poids avec un diviseur codé en dur dérive en silence : les poids et le diviseur sont
  deux vérités à maintenir ensemble. Préférer des **parts normalisées sommant à 1**, le diviseur
  disparaît et l'écart devient impossible.
- Un chiffre « plausible » écrit à la main (courbe horaire, forfait) doit porter sa source ou être
  signalé comme estimation : sans source, personne ne peut le contester ni le corriger.

## Mesure plutôt qu'estimation (2026-09-16)
- Un modèle « voyageurs par jour × part de l'heure » appliqué **par train** suppose sans le dire un train par minute :
  vérifier l'unité de chaque produit (voyageurs d'un train, pas d'une minute de ligne) en comparant à l'offre réelle.
- Le flux SIRI Estimated Timetable de PRIM : arrêts **non triés** dans la réponse, passé visible court
  (train en circulation : 1,2 min en médiane, p95 15 min ; train arrivé au terminus : ~14 min — mesuré le 22/09),
  statut `CANCELLED` par arrêt, `JourneyNote` = code mission, `DatedVehicleJourneyRef` contient l'uuid du trip GTFS
  **de la publication en cours** (les uuid changent à chaque publication GTFS : reconstruire les horaires),
  `STIF:StopArea:SP:<n>:` = `IDFM:monomodalStopPlace:<n>` du GTFS. Appel `LineRef=ALL` (tout le réseau, 1 requête, même compteur) : 4,5 Mo compressés sur le fil
  (gzip), 52 Mo de JSON, ~4 h 30 d'horizon contre ~2 h par ligne — mesuré le 17/09 ; le « 59 Mo » était la taille
  décompressée, pas le coût réseau.
- GTFS IDFM (117 Mo, 30 jours) : lire `stop_times.txt` en flux depuis le zip ; `route_id` = ligne PRIM sans `line:` ;
  le fichier ne contient pas de code UIC — rapprocher les comptages SNCF par les **mots du nom** de gare.
- Comptages SNCF : plusieurs campagnes pour une même gare (ex. J 2025 et 2026) — garder la plus récente, sinon on
  additionne deux années (J affiché à 280 000 au lieu de 205 000).
- Une vérification de quota se fait **par flux** : chaque produit PRIM a son propre `x-ratelimit-remaining-day`.
  Prochains passages (`stop-monitoring`, une requête par gare) : lui aussi 1 000/jour (17/09) — inutilisable pour
  suivre toutes les gares.
- Un retard annoncé longtemps à l'avance n'est pas une mesure : ne relever un arrêt qu'à moins de 10 min de son passage
  estimé, ce qui suppose un relevé plus fréquent que la fenêtre (5 min).
- Un serveur relancé par Claude Code survit à la session avec `nohup … & disown` (logs en `>>` dans `logs/uvicorn.log`).

## Plafond de retard
- Le plafond global (intervalle médian de la ligne) sous-estime les pertes en bout de branche et les
  surestime au tronc commun.
- (2026-09-17) Le plafond `60 / trains_gare` à la gare de destination était faux deux fois : `trains_gare` compte
  les **deux sens** (plafond divisé par deux), et un voyageur **à bord** ne peut pas prendre le train suivant.
  Un plafond ne s'applique qu'au voyageur à quai, sur le retard déjà présent à sa montée, et le train suivant
  doit desservir **sa gare de descente** (un train d'une autre branche ne sert à rien). Écart mesuré dans le flux ;
  un jour de panne le train suivant est aussi en retard. Effet : ×1,4 à ×1,6 sur les pertes des 15-17/09.
- Avant d'écrire qu'une grandeur est « par gare », vérifier l'unité dans le docstring du build (sens, jour type).
- `recalcul.py` boucle sur toute la plage premier → dernier incident : sur 148 jours, seuls 19 avaient
  des incidents. Pas de dégât, mais inutilement lent.

## Exploitation
- **Ne jamais tuber un script long dans `head`** : la fermeture du tube envoie un SIGPIPE et tue le
  script avant qu'il écrive son fichier de sortie. Rediriger vers un log puis `tail`, et vérifier le
  code retour.
- Changer la logique de calcul impose de recalculer l'historique **sur chaque PC** : les métriques
  dérivent des incidents bruts, mais chaque base a les siennes. Le JSON de profils est versionné, la
  base ne l'est pas.

## Fiabilité et « Mon trajet » (2026-09-17)
- Un arrêt garde en base la **dernière valeur vue avant de sortir du flux**. Le flux retire les arrêts dans l'ordre
  du parcours : un arrêt moins en retard qu'une gare précédente (au-delà du rattrapage possible) porte une valeur
  périmée — signature probable d'un arrêt sauté. Toujours vérifier la cohérence physique (arrivée ≥ départ + trajet).
- Tester le calcul contre **un trajet réellement vécu** : un seul cas (4 min comptées, ~20 vécues) a révélé le
  plafond faux, les arrêts sautés et les valeurs périmées. Noter heure du quai, mission affichée, heure d'arrivée.
- `sorted` sur des tuples `(datetime, dict)` plante à égalité d'heure : trier avec `key=`. Un redémarrage perd aussi
  la mémoire du relevé précédent (détection des arrêts sautés).
- `trip_id` GTFS = train des incidents : `rt_vehicle_journey:<trip_id>_AAAAMMJJ` (98 % de correspondance).
- Un fichier de données de quelques Mo fait échouer `git push` en HTTP 400 : `git -c http.postBuffer=524288000 push`.
- Chrome headless ne descend pas sous 500 px de large : tester le mobile dans une iframe de 360/390 px, ou par le
  protocole DevTools (`Emulation.setDeviceMetricsOverride`) ; pas de conclusion sur une capture rognée.
- Une page qui attend un premier choix (ligne) ne doit pas afficher ce choix estompé : il a l'air désactivé.

## Flux temps réel et trains bloqués (2026-09-17)
- Sur PRIM, un train immobilisé (coupure, panne) a une heure estimée qui recule avec l'horloge (≈ relevé + 3 min) :
  il ressemble à un train fantôme. Avant de déclarer une donnée fausse, vérifier les perturbations déclarées de la
  ligne et la suite du train dans les archives (reprise de marche = retard réel). Le SICA de 198 min était réel.
- Rejouer une règle de détection sur les archives d'une journée avec incident avant de la coder : c'est ce qui a
  montré qu'une détection de glissement aurait effacé les plus gros retards réels.
- Passé visible (mesuré le 22/09 sur 142 relevés du flux global) : le « 30 à 60 min » du 17/09 mélangeait trains
  terminés (qui restent ~14 min) et arrêts supprimés (datés à l'heure prévue). Le flux ne retire pas les arrêts dans
  l'ordre du parcours : une règle qui le suppose (arrêts sautés) se trompe 6 fois sur 10.
- Un diagnostic qui signale 100 % d'anomalies sur toutes les lignes mesure son propre défaut, pas le réseau : vérifier
  d'abord la jointure (le 22/09, uuid GTFS périmés).
- `RecordedAtTime` d'un train est ancien pour la plupart des trains (plus d'une heure) : inutilisable seul pour dire
  qu'une estimation est figée.

## Fenêtre de mesure et flags sticky (2026-09-17)
- Un flag d'arrêt (`s`, `k`) mis à `False` hors de la fenêtre de mesure (au lieu de `None`) empêche
  `fusionner_arrets` de conserver la mesure précédente. Règle : hors fenêtre → `None` (pas de mesure),
  dans la fenêtre → valeur réelle. Tout champ devant survivre à la fusion doit être dans la liste de
  conservation de `fusionner_arrets`.
- `is_cancelled` en base ne doit jamais régresser de `True` à `False` par un upsert qui voit le train
  sans arrêts supprimés dans la fenêtre — les arrêts sortent de la fenêtre avant que le train sorte du
  flux. L'upsert doit préserver la valeur existante (`Incident.is_cancelled`).
- Comparer GTFS vs flux pour détecter des trains absents est faisable mais ne doit pas créer d'incidents
  automatiquement : l'absence peut être un trou PRIM (confirmé pour la ligne K).

## Démarrage / double collecte (2026-09-21)
- Le log de démarrage donne le quota Estimated Timetable restant : proche de 1 000 en journée → aucun autre PC ne
  collecte. Vérification gratuite (pas de requête en plus) de la règle « un seul serveur à la fois ».

## Invariants et données de référence (2026-09-22 → 24)
- Un invariant à sens unique (« cet état ne régresse jamais ») n'est vrai que tant que la mesure qui le motivait
  reste imprécise : quand la mesure s'affine (arrêt hors fenêtre passé de `False` à `None`), il se met à compter des
  cas faux — 42 suppressions levées comptées pendant une semaine. Relire les invariants après chaque gain de précision.
- Une donnée de référence versionnée (GTFS, profils) doit porter un contrôle de jointure au moment de s'en servir :
  le GTFS IDFM a été republié deux fois en trois jours, avec de nouveaux `trip_id` à chaque fois, et rien ne le
  signalait — « Mon trajet » affichait simplement tous les trains à l'heure.
- Un warning ne suffit pas si personne ne lit les logs : le 24/09, les horaires sont restés périmés ~10 h. Ce qui
  doit être surveillé en continu appartient à une page ou à une alerte, pas à un fichier de log.
- Avant de coder une règle de détection, la rejouer sur les archives ET compter ses faux positifs par une mesure
  indépendante (ici : le passage estimé était-il déjà dépassé ?) — 61 % des « arrêts sautés » n'en étaient pas.

## Double collecte (2026-09-28)
- Le quota restant au démarrage ne prouve « aucun autre serveur » qu'à cet instant : un serveur resté allumé des jours
  sur l'autre PC n'apparaît pas au `/start` local. Avant de relancer un serveur, demander explicitement si l'autre PC
  en fait tourner un ; à `/wrap`, noter dans SESSION.md si un serveur reste allumé et sur quel PC.
- Deux collectes parallèles se fusionnent sans double comptage (clé `navitia_id`, union des trains) et se complètent
  (chaque PC a ses trous : veille, lancement tardif). Une fusion proche de la somme des deux n'est pas un doublon :
  vérifier les clés communes avant de conclure.
- Exporter la base locale **avant** le `git pull` : l'export écrit `transferts/incidents-<date>.json`, le même nom
  que les fichiers de l'autre PC — renommer en `-mac.json` pour ne rien écraser.

## Collecte interrompue (2026-09-29 → 30)
- Ce qu'une SESSION.md de l'autre PC affirme (« serveur lancé ») n'est pas un état vérifié : un serveur s'arrête sans
  prévenir. Seules preuves : heure du dernier incident en base et quota restant au premier relevé.
- Claude Code peut lancer le serveur de façon durable : `nohup caffeinate -i ./venv/bin/python -m uvicorn … >>
  logs/uvicorn.out 2>&1 < /dev/null & disown` survit à la commande (un simple `run_in_background` est tué).
