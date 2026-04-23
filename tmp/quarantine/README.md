# Quarantine

Archivos movidos aquí en F1-T3 para sacarlos de la raíz del repo sin borrar el trabajo.
Revisar manualmente antes de borrar en una release futura.

| Archivo | Origen | Motivo |
|---|---|---|
| `patch_live_brain_stable.py` | raíz (32 KB, untracked) | Script de patch one-off; no ejecutado por ningún entrypoint |
| `test_conversation_history_in_prompt.py` | raíz (tracked) | Test huérfano. Los tests vivos están en `tests/` |
| `test_cv_text_flow.py` | raíz (tracked) | Test huérfano |
| `test_llm_direct.py` | raíz (tracked) | Test huérfano |

Criterio para promover o borrar: si en los próximos 30 días no se referencia desde la suite oficial, borrar.

También se removió `~$_Daniel_Alarcon-26.docx` (lock de Word) como parte de F1-T3.
