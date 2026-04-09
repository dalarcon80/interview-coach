# Interview Coach — Audit Protocol for Orchestrator Agent

## Objetivo
Auditar cada salida de Kilo antes de permitir el siguiente paso.

## Auditoría por task
### Checklist duro
- [ ] Kilo trabajó solo en `allowed_files`
- [ ] Ejecutó todos los comandos exigidos
- [ ] Ejecutó todas las pruebas exigidas
- [ ] Reportó resultados completos
- [ ] No dejó TODOs en el camino crítico
- [ ] No cambió arquitectura congelada
- [ ] `config/status.json` fue actualizado
- [ ] Si cambió decisión técnica, `config/decisions.md` fue actualizado

### Evidencia mínima aceptable
1. diff de archivos
2. salida de comandos
3. salida de pruebas
4. pass/fail por criterio
5. blockers

## Auditoría por fase
### F0
- bootstrap pasa
- doctor pasa
- `/health` real
- suite base verde

### F1
- audio happy path real
- transcript live
- ES/EN visible
- persistencia básica
- 10 min sin crash

### F2
- ingestion real
- analyzer útil
- quality gate funcionando
- no mezcla de idiomas en final
- tracker actualiza claims/metrics_used/gaps

### F3
- 4 estilos
- settings persisten
- stealth/hotkeys
- replay
- persist queue robusta

### F4
- simulaciones
- benchmarks
- estabilidad 30 min

### F5
- adapters preparados sin romper V1 local-first

## Rechazos automáticos
Rechaza la task si:
- no corrió pruebas,
- dejó rojo algo obligatorio,
- reportó “debería funcionar” sin evidencia,
- tocó archivos fuera de scope,
- introdujo SQLite, ChromaDB o event backbone como pilar,
- convirtió el workflow en “multi-agent” otra vez.
