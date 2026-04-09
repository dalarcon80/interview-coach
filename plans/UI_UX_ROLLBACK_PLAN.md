# UI/UX Rollback Plan

**Versión:** 1.0  
**Fecha:** 2026-03-20  
**Objetivo de Rollback:** `backup/v1.0/`  
**Tiempo Máximo de Ejecución:** < 2 minutos

---

## 1. Estado Actual (Pre-UI/UX)

### 1.1 Archivos UI Actuales

| Archivo | Ubicación Actual | Estado |
|---------|------------------|--------|
| App.tsx | `tauri-app/src/App.tsx` | ~95,049 bytes |
| styles.css | `tauri-app/src/styles.css` | 2,390 bytes |
| tailwind.config.js | `tauri-app/tailwind.config.js` | 2,321 bytes |

### 1.2 Configuración de Colores Actual

El tema actual utiliza variables HSL en `styles.css`:
- `--background: 222.2 84% 4.9%` (tema oscuro)
- `--primary: 210 40% 98%`
- `--foreground: 210 40% 98%`
- Colores primario: escala blue (50-900)

### 1.3 Propuesta UI/UX a Implementar

Según [`docs/UI_UX_DESIGN_PROPOSAL.md`](docs/UI_UX_DESIGN_PROPOSAL.md):
- Nueva paleta de colores: Background Primary `#0a0f1a`, Accent `#0ea5e9`
- Custom colors en Tailwind: `interview.bg.primary`, `interview.text.primary`, etc.
- Nuevo sistema tipográfico
- Cambios en componentes: Live Captions, Conversation History, Real-Time Indicators

---

## 2. Puntos de Control (Checkpoints)

### 2.1 Fases de Implementación

| Fase | Descripción | Archivos a Modificar | Checkpoint |
|------|-------------|---------------------|------------|
| **Fase 1** | Configuración Tailwind + Colors | `tailwind.config.js`, `styles.css` | `backup/v1.0/` |
| **Fase 2** | Estilos de Componentes | `styles.css` | `backup/ui-ux-fase1/` |
| **Fase 3** | Actualización App.tsx | `App.tsx` | `backup/ui-ux-fase2/` |
| **Fase 4** | Componentes React | `components/*` | `backup/ui-ux-fase3/` |

### 2.2 Comandos de Backup (Antes de Cada Fase)

```bash
# ============================================
# BACKUP COMMANDS - Ejecutar antes de cada fase
# ============================================

# Backup actual (ya existe)
mkdir -p backup/v1.0

# Backup Fase 1 (Tailwind + Colors)
mkdir -p backup/ui-ux-fase1
cp tauri-app/src/App.tsx backup/ui-ux-fase1/
cp tauri-app/tailwind.config.js backup/ui-ux-fase1/
cp tauri-app/src/styles.css backup/ui-ux-fase1/
echo "Backup Fase 1 complete"

# Backup Fase 2 (Estilos de Componentes) - ejecutar después de Fase 1
mkdir -p backup/ui-ux-fase2
cp tauri-app/tailwind.config.js backup/ui-ux-fase2/
cp tauri-app/src/styles.css backup/ui-ux-fase2/
echo "Backup Fase 2 complete"

# Backup Fase 3 (App.tsx) - ejecutar después de Fase 2
mkdir -p backup/ui-ux-fase3
cp tauri-app/src/App.tsx backup/ui-ux-fase3/
echo "Backup Fase 3 complete"

# Backup Fase 4 (Componentes) - ejecutar después de Fase 3
mkdir -p backup/ui-ux-fase4
cp -r tauri-app/src/components/* backup/ui-ux-fase4/
echo "Backup Fase 4 complete"
```

---

## 3. Comandos de Rollback (Copy-Paste Listos)

### 3.1 Rollback Completo (Todas las Fases)

```bash
# ============================================
# ROLLBACK COMPLETO - UI/UX
# Tiempo estimado: ~30 segundos
# ============================================

# Restaurar App.tsx
cp backup/v1.0/App.tsx tauri-app/src/App.tsx

# Restaurar Tailwind config
cp backup/v1.0/tailwind.config.js tauri-app/tailwind.config.js

# Restaurar styles.css (si existe backup)
cp tauri-app/src/styles.css tauri-app/src/styles.css 2>/dev/null || echo "styles.css unchanged"

echo "Rollback completo ejecutado - Recargar Tauri app"
```

### 3.2 Rollback por Fase Específica

```bash
# ============================================
# ROLLBACK FASE 1: Tailwind + Colors
# Tiempo estimado: ~15 segundos
# ============================================
cp backup/ui-ux-fase1/tailwind.config.js tauri-app/tailwind.config.js
cp backup/ui-ux-fase1/styles.css tauri-app/src/styles.css
echo "Rollback Fase 1 complete"

# ============================================
# ROLLBACK FASE 2: Estilos de Componentes
# Tiempo estimado: ~15 segundos
# ============================================
cp backup/ui-ux-fase2/styles.css tauri-app/src/styles.css
echo "Rollback Fase 2 complete"

# ============================================
# ROLLBACK FASE 3: App.tsx
# Tiempo estimado: ~10 segundos
# ============================================
cp backup/ui-ux-fase3/App.tsx tauri-app/src/App.tsx
echo "Rollback Fase 3 complete"

# ============================================
# ROLLBACK FASE 4: Componentes React
# Tiempo estimado: ~20 segundos
# ============================================
cp -r backup/ui-ux-fase4/* tauri-app/src/components/
echo "Rollback Fase 4 complete"
```

### 3.3 Rollback Rápido (Un Comando)

```bash
# ============================================
# ROLLBACK RÁPIDO - Un solo comando
# ============================================
cp backup/v1.0/App.tsx tauri-app/src/App.tsx && cp tauri-app/tailwind.config.js tauri-app/tailwind.config.js.bak && git checkout tauri-app/tailwind.config.js && cp backup/v1.0/styles.css tauri-app/src/styles.css 2>/dev/null || true && echo "Fast rollback complete"
```

---

## 4. Procedimiento de Verificación Post-Rollback

### 4.1 Checklist de Verificación

```bash
# ============================================
# VERIFICACIÓN POST-ROLLBACK
# ============================================

echo "=== VERIFICACIÓN POST-ROLLBACK ==="

# 1. Verificar que App.tsx fue restaurado
echo "[1/5] Verificando App.tsx..."
if grep -q "InterviewCoach" tauri-app/src/App.tsx; then
    echo "  ✓ App.tsx正确 restaurado"
else
    echo "  ✗ App.tsx puede tener problemas"
fi

# 2. Verificar tailwind.config.js
echo "[2/5] Verificando tailwind.config.js..."
if grep -q "hsl(var" tauri-app/tailwind.config.js; then
    echo "  ✓ tailwind.config.js usa variables HSL"
else
    echo "  ✗ tailwind.config.js puede estar modificado"
fi

# 3. Verificar styles.css
echo "[3/5] Verificando styles.css..."
if grep -q "--background: 222.2 84% 4.9%" tauri-app/src/styles.css; then
    echo "  ✓ styles.css tiene tema oscuro original"
else
    echo "  ✗ styles.css puede estar modificado"
fi

# 4. Verificar que no hay errores de sintaxis
echo "[4/5] Verificando sintaxis TypeScript..."
cd tauri-app && npx tsc --noEmit 2>&1 | head -20

# 5. Verificar compilación Tailwind
echo "[5/5] Verificando compilación Tailwind..."
npx tailwindcss -i src/styles.css -o /dev/null 2>&1 | head -5

echo "=== VERIFICACIÓN COMPLETA ==="
```

### 4.2 Pasos Manuales de Verificación

1. **Recargar Tauri App**: Cerrar y abrir la aplicación de escritorio
2. **Verificar tema visual**:
   - El fondo debe ser oscuro (no negro puro)
   - Los colores deben ser los originales (azules)
   - No debe haber elementos de la nueva paleta (#0ea5e9 visible)
3. **Probar funcionalidad básica**:
   - Live Caption debe funcionar
   - Conversation History debe cargar
   - Settings deben abrirse
4. **Verificar consola** (dev mode):
   - No debe haber errores de React
   - No debe haber warnings de Tailwind

---

## 5. Criterios de Rollback

### 5.1 Cuándo Ejecutar Rollback

| Condición | Severidad | Acción |
|-----------|-----------|--------|
| Error de compilación TypeScript | Crítica | Rollback inmediato |
| Error de compilación Tailwind/CSS | Crítica | Rollback inmediato |
| App no inicia (crash) | Crítica | Rollback inmediato |
| Live Caption no funciona | Alta | Evaluar - podría ser otra causa |
| Problemas visuales menores | Media | Documentar, continuar desarrollo |
| Rendimiento degradado | Media | Documentar, investigar |

### 5.2 Condiciones de Error Específicas

```bash
# Error de sintaxis en App.tsx
# Symptoms: "SyntaxError", "Unexpected token" en consola
# → Rollback Fase 3

# Error en tailwind.config.js
# Symptoms: "Invalid config", colores no se aplican
# → Rollback Fase 1

# Estilos rotos en styles.css
# Symptoms: UI deformada, elementos superpuestos
# → Rollback a Fase anterior

# Componentes rotos
# Symptoms: Errores de imports, componentes no renderizan
# → Rollback Fase 4
```

### 5.3 Proceso de Decisión

```
┌─────────────────────────────────────┐
│ ¿La app compila sin errores?        │
└──────────────┬──────────────────────┘
               │
    ┌──────────┴──────────┐
    ↓                     ↓
   YES                    NO
    │                     │
    ↓                     ↓
┌─────────────┐    ┌──────────────────┐
│ ¿Funcional? │    │ Rollback completo │
└──────┬──────┘    └──────────────────┘
       │
       ↓
   ┌───┴───┐
   ↓       ↓
  YES     NO
   │       │
   ↓       ↓
CONTINUAR  Rollback
```

---

## 6. Restauración de Componentes de Estilos

### 6.1 Estilos CSS a Restaurar

```bash
# Restaurar solo styles.css (mantiene App.tsx)
cp backup/v1.0/styles.css tauri-app/src/styles.css
```

### 6.2 Restaurar Solo tailwind.config.js

```bash
# Restaurar configuración Tailwind
# Opción 1: Desde backup original
cp backup/v1.0/tailwind.config.js tauri-app/tailwind.config.js

# Opción 2: Valores por defecto
cat > tauri-app/tailwind.config.js << 'EOF'
import tailwindcssAnimate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
    },
  },
  plugins: [tailwindcssAnimate],
}
EOF
```

---

## 7. Notas Adicionales

### 7.1 Recomendaciones

1. **Siempre hacer backup antes de cada fase** - No omitir este paso
2. **Probar incrementally** - Después de cada fase, verificar que la app funciona
3. **Documentar cambios** - Registrar qué se cambió en cada fase para facilitar rollback selectivo
4. **Mantener backups pequenos** - Solo incluir archivos modificados, no todo el proyecto

### 7.2 Archivos Ignorados en Rollback

Los siguientes archivos NO se modifican en UI/UX y no requieren rollback:
- `python-core/*` - Backend
- `tauri-app/src-tauri/*` - Rust
- `tauri-app/src/lib/*` - Lógica de API (excepto cambios de UI)

### 7.3 Contacto para Soporte

Si el rollback no funciona como se espera:
1. Verificar que los archivos de backup existen: `ls -la backup/v1.0/`
2. Comparar diferencias: `diff backup/v1.0/App.tsx tauri-app/src/App.tsx`
3. Verificar permisos: `ls -la tauri-app/src/`

---

## 8. Resumen de Tiempos

| Operación | Tiempo Estimado |
|-----------|-----------------|
| Backup (todas las fases) | ~30 segundos |
| Rollback completo | ~30 segundos |
| Rollback por fase | ~15-20 segundos |
| Verificación post-rollback | ~1 minuto |
| **Total (worst case)** | **~2 minutos** |

---

*Documento creado según HR-3 de AGENTS.md - Rollback plan ejecutable en menos de 2 minutos*
