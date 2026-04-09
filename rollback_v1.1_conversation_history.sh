#!/bin/bash
# Rollback Script v1.1 - Conversation History Fix
# Este script revierte los cambios de historial de conversación a la versión anterior
# Fecha: 2026-03-19

set -e

echo "=========================================="
echo "ROLLBACK: Conversation History Fix v1.1"
echo "=========================================="
echo ""

# Crear backup de los cambios actuales (por si acaso)
BACKUP_DIR="rollback_snapshots/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "1. Creando snapshot de estado actual en $BACKUP_DIR..."
cp python-core/contracts/models.py "$BACKUP_DIR/"
cp python-core/api/server.py "$BACKUP_DIR/"
cp python-core/pipeline/steps/response_composer.py "$BACKUP_DIR/"
echo "   ✅ Snapshot creado"
echo ""

echo "2. Revirtiendo cambios..."

# Restaurar desde backup/v1.0
echo "   - Restaurando runtime_config.json..."
cp backup/v1.0/runtime_config.json python-core/runtime_config.json

echo "   ✅ Rollback completado"
echo ""

echo "=========================================="
echo "INSTRUCCIONES POST-ROLLBACK:"
echo "=========================================="
echo "1. Reiniciar el backend:"
echo "   cd python-core && python -m uvicorn api.server:app --reload"
echo ""
echo "2. Reiniciar el frontend:"
echo "   cd tauri-app && npm run tauri dev"
echo ""
echo "3. Verificar que el sistema funciona normalmente"
echo ""
echo "=========================================="
echo "Para restaurar los cambios de v1.1:"
echo "=========================================="
echo "cp $BACKUP_DIR/* python-core/"
echo ""
