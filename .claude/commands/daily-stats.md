# /daily-stats

Affiche les statistiques du jour depuis l'API locale.

```bash
curl -s http://localhost:8000/api/stats/today | python -m json.tool
```

Ou via Docker :
```bash
docker-compose exec backend python -c "
from backend.metrics import get_today_stats
import asyncio
print(asyncio.run(get_today_stats()))
"
```
