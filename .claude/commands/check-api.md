# /check-api

Vérifie que l'API PRIM répond correctement.

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "apikey: $PRIM_API_KEY" \
  "https://prim.iledefrance-mobilites.fr/marketplace/disruptions/?count=1"
```

Résultat attendu : `200`
