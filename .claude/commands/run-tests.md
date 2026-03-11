# /run-tests

Lance la suite de tests complète avec pytest.

```bash
cd /app && python -m pytest tests/ -v --tb=short 2>&1
```

Si Docker est actif :
```bash
docker-compose exec backend python -m pytest tests/ -v --tb=short
```
