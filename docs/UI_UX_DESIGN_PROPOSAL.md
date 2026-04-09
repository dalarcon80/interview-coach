# Interview Coach - UI/UX Design Proposal

## 1. Resumen Ejecutivo

Esta propuesta de diseño establece una nueva identidad visual para Interview Coach, enfocada en transmitir **confianza, profesionalismo y tecnología de punta**. El diseño está optimizado para el contexto de entrevistas virtuales donde el usuario necesita procesar información rápidamente mientras participa en una videollamada.

### Principios de Diseño

1. **Jerarquía de Información en Tiempo Real** - Los elementos más importantes (Live Captions) reciben prioridad visual máxima
2. **Separación Clara de Responsabilidades** - Cada componente (Captions, History, Suggestions) tiene identidad visual Distinct
3. **Fatiga Visual Mínima** - Colores oscuros con контрастantes достаточные para sesiones prolongadas
4. **Accesibilidad Integrada** - WCAG 2.1 AA como mínimo, con modo alto contraste opcional

### Objetivos Clave

- **Live Captions**: Alta visibilidad, lectura fácil, actualizaciones en tiempo real sin parpadeo excesivo
- **Conversation History**: Navegación clara, distinción de turnos, acceso rápido
- **Real-Time Conversation**: Diferenciación clara entre interlocutores,flow visual natural
- **Coach Suggestions**: Visibles pero no intrusivas, fáciles de ignorar si es necesario

---

## 2. Paleta de Colores Completa

### 2.1 Colores Base (Tema Oscuro)

| Nombre | HSL | Hex | Uso Principal |
|--------|-----|-----|----------------|
| Background Primary | 222° 47% 4.9% | `#0a0f1a` | Fondo principal de la aplicación |
| Background Secondary | 217° 33% 10% | `#111827` | Cards, paneles elevados |
| Background Tertiary | 215° 25% 14% | `#1e293b` | Áreas de input, campos |
| Surface | 214° 32% 18% | `#1e293b` | Superficies interactivas |

### 2.2 Colores de Texto

| Nombre | HSL | Hex | Ratio WCAG | Uso |
|--------|-----|-----|------------|-----|
| Text Primary | 210° 40% 98% | `#f1f5f9` | 15.4:1 | Texto principal, títulos |
| Text Secondary | 215° 20% 70% | `#94a3b8` | 4.5:1 | Metadata, timestamps |
| Text Muted | 215° 15% 50% | `#64748b` | 3.2:1 | Placeholders, hints |

### 2.3 Colores de Acento (Estados)

| Nombre | HSL | Hex | Ratio WCAG | Uso |
|--------|-----|-----|------------|-----|
| Accent Primary | 199° 89% 50% | `#0ea5e9` | 4.6:1 | Links, botones primarios, Live indicators |
| Accent Hover | 198° 91% 56% | `#38bdf8` | 4.5:1 | Estados hover |
| Success | 160° 84% 45% | `#22c55e` | 4.5:1 | Estado activo, conexión exitosa |
| Warning | 38° 92% 55% | `#f59e0b` | 4.4:1 | Estados de advertencia |
| Error | 0° 84% 60% | `#ef4444` | 4.5:1 | Errores, estados críticos |

### 2.4 Colores Específicos de Componentes

#### Live Captions

| Nombre | Hex | Uso |
|--------|-----|-----|
| Caption Background | `#0f172a` | Fondo del área de captions |
| Caption Border Active | `#0ea5e9` | Borde cuando hay actividad |
| Caption Text | `#f8fafc` | Texto del caption |
| Caption Partial | `#94a3b8` | Texto parcial (en transición) |
| Caption Indicator | `#22c55e` | Punto de actividad en tiempo real |

#### Conversation History

| Nombre | Hex | Uso |
|--------|-----|-----|
| History Card BG | `#111827` | Fondo de cada entrada |
| History Border | `#1e293b` | Bordes separadores |
| Interviewer Turn | `#1e293b` | Fondo para turnos del entrevistador |
| Candidate Turn | `#0f172a` | Fondo para turnos del candidato |
| Coach Response | `#1e1b4b` | Fondo especial para respuestas del coach |

#### Real-Time Indicators

| Nombre | Hex | Uso |
|--------|-----|-----|
| Listening Pulse | `#0ea5e9` | Animación de escucha activa |
| Processing | `#f59e0b` | Indicador de procesamiento |
| Idle | `#64748b` | Estado inactivo |

### 2.5 Implementación Tailwind CSS

```css
/* En tailwind.config.js - agregar custom colors */
colors: {
  interview: {
    bg: {
      primary: '#0a0f1a',
      secondary: '#111827',
      tertiary: '#1e293b',
      surface: '#1e293b',
    },
    text: {
      primary: '#f1f5f9',
      secondary: '#94a3b8',
      muted: '#64748b',
    },
    accent: {
      DEFAULT: '#0ea5e9',
      hover: '#38bdf8',
    },
    caption: {
      bg: '#0f172a',
      border: '#0ea5e9',
      text: '#f8fafc',
      partial: '#94a3b8',
      indicator: '#22c55e',
    },
    history: {
      card: '#111827',
      border: '#1e293b',
      interviewer: '#1e293b',
      candidate: '#0f172a',
      coach: '#1e1b4b',
    },
    status: {
      listening: '#0ea5e9',
      processing: '#f59e0b',
      idle: '#64748b',
      success: '#22c55e',
      error: '#ef4444',
    }
  }
}
```

---

## 3. Sistema Tipográfico

### 3.1 Familia Tipográfica

**Font Principal**: `Inter` (ya en uso)
- Excelente legibilidad en pantallas
- Variantes con buena ponderación
- Diseñado para interfaces

**Font Monospace** (para timestamps, IDs): `JetBrains Mono` o `Fira Code`
- Para datos técnicos: latencia, IDs de sesión, timestamps

### 3.2 Especificaciones por Nivel

| Nivel | Font | Size | Weight | Line Height | Letter Spacing |
|-------|------|------|--------|-------------|----------------|
| H1 (Page Title) | Inter | 28px / 1.75rem | 700 | 1.2 | -0.02em |
| H2 (Section) | Inter | 22px / 1.375rem | 600 | 1.3 | -0.01em |
| H3 (Card Title) | Inter | 18px / 1.125rem | 600 | 1.4 | 0 |
| Body Large | Inter | 16px / 1rem | 400 | 1.6 | 0 |
| Body | Inter | 14px / 0.875rem | 400 | 1.5 | 0 |
| Caption | Inter | 12px / 0.75rem | 500 | 1.4 | 0.02em |
| Overline | Inter | 11px / 0.6875rem | 600 | 1.3 | 0.08em |
| Mono (Data) | JetBrains Mono | 12px / 0.75rem | 400 | 1.4 | 0 |

### 3.3 Tipografía por Componente

#### Live Captions (Prioridad Máxima)

```css
/* Texto principal de caption */
.caption-text {
  font-family: 'Inter', sans-serif;
  font-size: 1.25rem;    /* 20px */
  font-weight: 400;
  line-height: 1.6;
  letter-spacing: 0.01em;
  color: #f8fafc;
}

/* Texto parcial (mientras habla) */
.caption-partial {
  font-family: 'Inter', sans-serif;
  font-size: 1.25rem;
  font-weight: 400;
  line-height: 1.6;
  color: #94a3b8;  /* Más suave para texto en transición */
  font-style: italic;
}
```

#### Conversation History

```css
/* Título de entrada en el historial */
.history-title {
  font-family: 'Inter', sans-serif;
  font-size: 0.9375rem;  /* 15px */
  font-weight: 500;
  line-height: 1.4;
  color: #f1f5f9;
}

/* Preview/Excerpt */
.history-preview {
  font-family: 'Inter', sans-serif;
  font-size: 0.8125rem;  /* 13px */
  font-weight: 400;
  line-height: 1.5;
  color: #94a3b8;
}

/* Timestamp */
.history-timestamp {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6875rem;  /* 11px */
  font-weight: 400;
  color: #64748b;
}
```

#### Coach Suggestions (Full Response)

```css
/* Título de sección */
.suggestion-header {
  font-family: 'Inter', sans-serif;
  font-size: 0.75rem;  /* 12px */
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0ea5e9;
}

/* Respuesta completa */
.suggestion-body {
  font-family: 'Inter', sans-serif;
  font-size: 1rem;  /* 16px */
  font-weight: 400;
  line-height: 1.75;
  color: #f1f5f9;
}

/* Bullets/Puntos clave */
.suggestion-bullet {
  font-family: 'Inter', sans-serif;
  font-size: 0.875rem;  /* 14px */
  font-weight: 400;
  line-height: 1.6;
  color: #cbd5e1;
}
```

### 3.4 Tailwind CSS Classes

```javascript
// tailwind.config.js - agregar extend
theme: {
  extend: {
    fontSize: {
      'caption-lg': '1.25rem',    // 20px - Live captions
      'caption': '1rem',          // 16px - Regular captions
      'overline': '0.6875rem',    // 11px
    },
    letterSpacing: {
      'caption': '0.01em',
      'tight-sm': '0.02em',
    }
  }
}
```

---

## 4. Especificaciones de Componentes Visuales

### 4.1 Live Captions

#### Posicionamiento y Layout

```
┌─────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────┐   │
│  │ 🔴 LIVE CAPTIONS              [─] [□] [×]  │   │  <- Header con controls
│  ├─────────────────────────────────────────────┤   │
│  │                                             │   │
│  │  "Tell me about a challenging..."          │   │  <- Current caption
│  │                                             │   │
│  │  ─────────────────────────────────────      │   │  <- Divider
│  │                                             │   │
│  │  "So, in my previous role at..."          │   │  <- Previous context
│  │                                             │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### Especificaciones Visuales

| Elemento | Especificación |
|----------|----------------|
| Contenedor | `bg-caption-bg`, `rounded-lg`, `border border-caption-border` |
| Header | `flex items-center justify-between`, `border-b border-caption-border` |
| Indicador Live | `w-2 h-2 rounded-full bg-status-listening animate-pulse` |
| Texto Principal | `text-caption-text text-caption-lg leading-relaxed` |
| Texto Parcial | `text-caption-partial italic` |
| Scroll | Auto-scroll con animation suave, máximo 5 líneas visibles |

#### Animaciones

```css
/* Transición de texto parcial a final */
.caption-transition {
  transition: all 150ms ease-out;
}

/* Efecto de typing para nuevos captions */
@keyframes caption-appear {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.caption-new {
  animation: caption-appear 200ms ease-out;
}
```

#### Clases Tailwind Sugeridas

```jsx
// Componente LiveCaption
<div className="
  bg-caption-bg
  border border-caption-border
  rounded-lg
  overflow-hidden
  shadow-lg
">
  {/* Header */}
  <div className="
    flex items-center justify-between
    px-4 py-3
    border-b border-caption-border
    bg-background-secondary
  ">
    <div className="flex items-center gap-2">
      <span className="
        w-2 h-2 rounded-full
        bg-status-listening
        animate-pulse
      " />
      <span className="
        text-overline
        font-semibold
        tracking-wider
        uppercase
        text-accent
      ">
        Live Caption
      </span>
    </div>
    {/* Controls: minimize, maximize, close */}
  </div>

  {/* Caption Content */}
  <div className="p-4 max-h-[200px] overflow-y-auto">
    <p className="text-caption-text text-caption-lg leading-relaxed">
      {transcript}
    </p>
  </div>
</div>
```

### 4.2 Conversation History

#### Layout Estructural

```
┌─────────────────────────────────────────────────────┐
│  CONVERSATION HISTORY                    [Clear]  │
├─────────────────────────────────────────────────────┤
│  ▼ 10:32:15 • Question about leadership      [Q]  │
│    "Tell me about a time you led a team..."       │
│    ──────────────────────────────────────────     │
│    Answer preview text here...                     │
│                                                     │
│  ▼ 10:28:42 • Technical question             [Q]  │
│    "What's your experience with React?"           │
│    ──────────────────────────────────────────     │
│    Answer preview text here...                     │
│                                                     │
│  ▼ 10:15:30 • Cultural fit                    [Q]  │
│    "What type of work environment..."              │
│    ──────────────────────────────────────────     │
│    Answer preview text here...                     │
└─────────────────────────────────────────────────────┘
```

#### Especificaciones Visuales

| Elemento | Especificación |
|----------|----------------|
| Contenedor Principal | `bg-history-card`, `rounded-xl`, `shadow-md` |
| Accordion Item | `border-b border-history-border` |
| Header (cerrado) | `flex items-center gap-3`, `py-3 px-4` |
| Badge de Tipo | `px-2 py-0.5 rounded text-xs font-medium` |
| Indicador de Turno | `w-1 h-8 rounded-full` (entrevistador/candidato) |
| Timestamp | `font-mono text-xs text-text-muted` |
| Preview Text | `text-sm text-text-secondary line-clamp-2` |

#### Distinción de Turnos

```css
/* Turno del entrevistador - lado izquierdo */
.turn-interviewer {
  background-color: #1e293b;
  border-left: 3px solid #64748b;
}

/* Turno del candidato - indentado */
.turn-candidate {
  background-color: #0f172a;
  border-left: 3px solid #0ea5e9;
}

/* Respuesta del coach - especial */
.turn-coach {
  background: linear-gradient(135deg, #1e1b4b 0%, #1e293b 100%);
  border-left: 3px solid #8b5cf6;
}
```

#### Clases Tailwind Sugeridas

```jsx
// Componente ConversationHistory
<div className="
  bg-history-card
  rounded-xl
  shadow-md
  border border-history-border
  overflow-hidden
">
  <div className="
    flex items-center justify-between
    px-4 py-3
    border-b border-history-border
  ">
    <h3 className="text-lg font-semibold text-text-primary">
      Conversation History
    </h3>
    <Button variant="ghost" size="sm">Clear</Button>
  </div>

  <ScrollArea className="h-[520px]">
    <Accordion type="single" collapsible>
      {entries.map((entry) => (
        <AccordionItem
          key={entry.id}
          value={entry.id}
          className={`
            border-b border-history-border
            ${entry.speaker === 'interviewer' ? 'bg-history-interviewer' : 'bg-history-candidate'}
          `}
        >
          <AccordionTrigger className="px-4 hover:no-underline">
            <div className="flex items-center gap-3 w-full">
              {/* Turn indicator */}
              <div className={`
                w-1 h-8 rounded-full
                ${entry.speaker === 'interviewer' ? 'bg-slate-500' : 'bg-accent'}
              `} />

              <div className="flex-1 text-left">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-text-muted">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {entry.type}
                  </Badge>
                </div>
                <p className="text-sm font-medium text-text-primary line-clamp-1">
                  {entry.question}
                </p>
              </div>
            </div>
          </AccordionTrigger>

          <AccordionContent className="px-4 pb-4">
            <div className="space-y-3">
              {/* Full question/answer */}
              <div className="text-sm text-text-secondary leading-relaxed">
                {entry.content}
              </div>

              {/* Coach suggestion if available */}
              {entry.suggestion && (
                <div className="
                  p-3 rounded-lg
                  bg-history-coach
                  border border-purple-500/30
                ">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles className="w-4 h-4 text-purple-400" />
                    <span className="text-xs font-semibold text-purple-400">
                      Coach Suggestion
                    </span>
                  </div>
                  <p className="text-sm text-text-secondary">
                    {entry.suggestion.summary}
                  </p>
                </div>
              )}
            </div>
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  </ScrollArea>
</div>
```

### 4.3 Real-Time Conversation

#### Layout de Diálogo

```
┌─────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────┐   │
│  │ 👤 Entrevistador                              │   │
│  │ "Can you describe a situation where..."    │   │
│  │ ─────────────────────────────────────────   │   │
│  │ 10:32:15 • Duration: 8s                    │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ 🎤 Tú (candidato)                            │   │
│  │ "In my previous role at Company X..."       │   │
│  │ ─────────────────────────────────────────   │   │
│  │ 10:32:23 • Duration: 45s                   │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ 💡 Coach                                    │   │
│  │ "Consider adding a specific metric..."     │   │
│  │ ─────────────────────────────────────────   │   │
│  │ [View full suggestion]                     │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### Especificaciones Visuales

| Elemento | Especificación |
|----------|----------------|
| Contenedor de Mensaje | `rounded-xl p-4`, diferentes colores según hablante |
| Avatar/Icono | `w-8 h-8 rounded-full flex items-center justify-center` |
| Nombre/Hablante | `text-sm font-semibold` |
| Texto del Mensaje | `text-base leading-relaxed` |
| Metadata | `text-xs text-text-muted font-mono` |

#### Estilos por Tipo de Hablante

```css
/* Entrevistador */
.message-interviewer {
  background-color: #1e293b;
  border-left: 4px solid #64748b;
}

.message-interviewer .avatar {
  background-color: #64748b;
}

/* Candidato */
.message-candidate {
  background-color: #0f172a;
  border-left: 4px solid #0ea5e9;
}

.message-candidate .avatar {
  background-color: #0ea5e9;
}

/* Coach */
.message-coach {
  background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
  border-left: 4px solid #8b5cf6;
}

.message-coach .avatar {
  background: linear-gradient(135deg, #8b5cf6 0%, #0ea5e9 100%);
}
```

### 4.4 Sugerencias del Coach

#### Diseño de Tarjeta de Sugerencia

```
┌─────────────────────────────────────────────────────┐
│  💡 COACH SUGGESTION                    [Copy][×]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Full response text goes here. This can be         │
│  multiple paragraphs long and provides the         │
│  complete coaching response...                     │
│                                                     │
│  ──────────────────────────────────────────        │
│                                                     │
│  Key Points                                        │
│  • Focus on the STAR method                        │
│  • Quantify your achievements                      │
│  • Connect to the job requirements                 │
│                                                     │
│  ──────────────────────────────────────────        │
│                                                     │
│  Quality: 85%  |  Confidence: 92%  |  450ms        │
└─────────────────────────────────────────────────────┘
```

#### Especificaciones

| Elemento | Especificación |
|----------|----------------|
| Contenedor | `bg-history-card rounded-xl shadow-lg border border-accent/20` |
| Header | `flex items-center justify-between px-4 py-3 border-b` |
| Badge de Calidad | `bg-green-500/20 text-green-400 px-2 py-1 rounded` |
| Badge de Confianza | `bg-blue-500/20 text-blue-400 px-2 py-1 rounded` |
| Latencia | `text-text-muted font-mono text-xs` |

---

## 5. Guía de Espaciado y Layout

### 5.1 Sistema de Grid

```css
/* Tailwind grid - 12 columnas */
grid-template-columns: repeat(12, minmax(0, 1fr));

/* Gap base: 4px (0.25rem) */
gap-1;   /* 4px  - elementos muy cercanos */
gap-2;   /* 8px  - elementos relacionados */
gap-3;   /* 12px - grupos de elementos */
gap-4;   /* 16px - secciones */
gap-6;   /* 24px - áreas grandes */
gap-8;   /* 32px - separación principal */
```

### 5.2 Layout Principal

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER: Logo | Nav Tabs | Status Indicators | Settings   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────┐  ┌─────────────────────────┐    │
│  │                     │  │                         │    │
│  │   LIVE CAPTIONS     │  │   COACH RESPONSE        │    │
│  │   (Primary)         │  │   (Full Response)       │    │
│  │                     │  │                         │    │
│  │   Height: 200-300px │  │   Height: flexible      │    │
│  │   Width: 35-40%    │  │   Width: 60-65%        │    │
│  │                     │  │                         │    │
│  └─────────────────────┘  └─────────────────────────┘    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                       │   │
│  │   CONVERSATION HISTORY                               │   │
│  │   (Scrollable, collapsible entries)                 │   │
│  │                                                       │   │
│  │   Height: 400-500px                                   │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 Breakpoints Responsive

| Breakpoint | Width | Layout |
|------------|-------|--------|
| sm | 640px | Single column, stacked |
| md | 768px | Two columns for captions + response |
| lg | 1024px | Full layout with side-by-side |
| xl | 1280px | Optimal layout, max content width 1200px |
| 2xl | 1536px | Same as xl, centered |

#### Clases Tailwind para Layout

```jsx
// Layout responsive
<div className="
  grid
  grid-cols-1
  md:grid-cols-2
  lg:grid-cols-12
  gap-4
  p-4
">
  {/* Live Captions - toma 4 columnas en lg */}
  <div className="lg:col-span-4">
    <LiveCaption />
  </div>

  {/* Coach Response - toma 8 columnas en lg */}
  <div className="lg:col-span-8">
    <SuggestionDisplay />
  </div>

  {/* Conversation History - ancho completo */}
  <div className="col-span-1 lg:col-span-12">
    <ConversationHistory />
  </div>
</div>
```

### 5.4 Espaciado Interior (Padding)

```css
/* Padding por componente */
.padding-sm   /* 8px  (0.5rem)  - badges, tags */
.padding-md   /* 12px (0.75rem) - buttons, small cards */
.padding-lg   /* 16px (1rem)    - list items */
.padding-xl   /* 24px (1.5rem)  - cards, panels */
.padding-2xl  /* 32px (2rem)    - main sections */
```

### 5.5 Sombras y Profundidad

| Nivel | Shadow CSS | Uso |
|-------|------------|-----|
| sm | `0 1px 2px rgba(0,0,0,0.3)` | Elementos sutiles |
| md | `0 4px 6px rgba(0,0,0,0.3)` | Cards, dropdowns |
| lg | `0 10px 15px rgba(0,0,0,0.3)` | Modals, overlays |
| xl | `0 20px 25px rgba(0,0,0,0.3)` | Paneles principales |
| glow-blue | `0 0 20px rgba(14,165,233,0.3)` | Estados activos |
| glow-purple | `0 0 20px rgba(139,92,246,0.3)` | Coach suggestions |

---

## 6. Indicadores de Estado

### 6.1 Indicadores Visuales

#### Estado de Conexión (WebSocket)

| Estado | Visual | Color | Animación |
|--------|--------|-------|-----------|
| Conectado | ● Punto sólido | `#22c55e` (success) | Ninguna |
| Conectando | ◐ Punto medio | `#f59e0b` (warning) | Pulse |
| Desconectado | ○ Círculo vacío | `#ef4444` (error) | Ninguna |
| Error | ⚠ Icono | `#ef4444` | Shake |

```jsx
// Componente ConnectionStatus
const ConnectionStatus = ({ status }) => {
  const statusConfig = {
    connected: {
      icon: <Wifi className="w-4 h-4" />,
      color: 'text-status-success',
      bgColor: 'bg-status-success/20',
      label: 'Connected',
      animation: 'none'
    },
    connecting: {
      icon: <Wifi className="w-4 h-4" />,
      color: 'text-status-processing',
      bgColor: 'bg-status-processing/20',
      label: 'Connecting...',
      animation: 'animate-pulse'
    },
    disconnected: {
      icon: <WifiOff className="w-4 h-4" />,
      color: 'text-status-error',
      bgColor: 'bg-status-error/20',
      label: 'Disconnected',
      animation: 'none'
    }
  };

  const config = statusConfig[status];

  return (
    <div className={`
      inline-flex items-center gap-2
      px-3 py-1.5 rounded-full
      ${config.bgColor}
      ${config.color}
      ${config.animation}
    `}>
      {config.icon}
      <span className="text-xs font-medium">{config.label}</span>
    </div>
  );
};
```

#### Estado de Escucha (STT Activo)

| Estado | Visual | Color |
|--------|--------|-------|
| Escuchando | 🎤 Mic icon + onda | `#0ea5e9` (accent) |
| Procesando | 🔄 Spinner | `#f59e0b` (warning) |
| Silencio | 🎤 Mic (muted) | `#64748b` (idle) |
| Inactivo | ○ Estado idle | `#64748b` (muted) |

```jsx
// Listening indicator con onda de sonido
<div className="flex items-center gap-2">
  {/* Animated sound waves */}
  <div className="flex items-end gap-0.5 h-4">
    <span className="w-0.5 bg-status-listening animate-pulse" style={{ height: '40%' }} />
    <span className="w-0.5 bg-status-listening animate-pulse" style={{ height: '70%', animationDelay: '100ms' }} />
    <span className="w-0.5 bg-status-listening animate-pulse" style={{ height: '100%', animationDelay: '200ms' }} />
    <span className="w-0.5 bg-status-listening animate-pulse" style={{ height: '60%', animationDelay: '300ms' }} />
    <span className="w-0.5 bg-status-listening animate-pulse" style={{ height: '30%', animationDelay: '400ms' }} />
  </div>
  <span className="text-xs font-medium text-status-listening">
    Listening
  </span>
</div>
```

#### Estado de Procesamiento (Coach)

| Estado | Visual | Color | Tiempo estimado |
|--------|--------|-------|-----------------|
| Generando | ⏳ Progress bar | `#f59e0b` | 0-3s |
| Completo | ✓ Check | `#22c55e` | - |
| Error | ✕ X | `#ef4444` | - |
| Optimizando | ⚡ Lightning | `#0ea5e9` | <1s |

### 6.2 Posicionamiento de Indicadores

```
┌─────────────────────────────────────────────────────────────┐
│  Header Bar: [Status] [Session Info]        [Settings ⚙]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [● Live] [● Connected]     Session: 12:34    [?] [Settings]│
│                                                             │
│  ┌─────────────────────┐  ┌─────────────────────────┐      │
│  │ 🔴 LIVE CAPTIONS     │  │ 💡 Coach Response      │      │
│  │ [Processing...]      │  │ [Generating...]         │      │
│  └─────────────────────┘  └─────────────────────────┘      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Mockups/Wireframes Descriptivos

### 7.1 Vista Principal - Coach Tab

```
┌────────────────────────────────────────────────────────────────────┐
│  INTERVIEW COACH              [Connection: ● Connected]    [⚙]   │
├────────────────────────────────────────────────────────────────────┤
│  [Coach] [Live]                                                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────────────────┐ ┌────────────────────────────┐   │
│  │  🔴 LIVE CAPTIONS            │ │ 💡 COACHING RESPONSE     │   │
│  │  ─────────────────────       │ │ ─────────────────────     │   │
│  │                              │ │ Quality: 85%  Conf: 92%   │   │
│  │  "Tell me about a time      │ │                          │   │
│  │   you handled a difficult   │ │ Here's a strong response │   │
│  │   customer situation..."    │ │ using the STAR method:   │   │
│  │                              │ │                          │   │
│  │  ─────────────────────       │ │ **Situation**: At my     │   │
│  │                              │ │ previous role as a       │   │
│  │  Previous: "So, at my        │ │ customer support lead,   │   │
│  │  previous company..."        │ │ we faced a critical...  │   │
│  │                              │ │                          │   │
│  │                              │ │ **Task**: The client     │   │
│  │                              │ │ was experiencing...      │   │
│  │                              │ │                          │   │
│  │ [◉ Listening] [⚡ 45ms]      │ │ [Copy] [Key Points ▼]   │   │
│  └──────────────────────────────┘ └────────────────────────────┘   │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  CONVERSATION HISTORY                               [Clear] │    │
│  │  ─────────────────────────────────────────────────────────  │    │
│  │  ▼ 10:45:32 • Leadership question                   [Q]   │    │
│  │     "Tell me about your leadership style..."                 │    │
│  │                                                               │    │
│  │  ▼ 10:42:15 • Technical - React                       [Q]   │    │
│  │     "What's your experience with React hooks?"              │    │
│  │                                                               │    │
│  │  ▼ 10:38:45 • Cultural fit                            [Q]   │    │
│  │     "What type of work environment..."                      │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 7.2 Vista Live Tab

```
┌────────────────────────────────────────────────────────────────────┐
│  INTERVIEW COACH                    [● Connected] [Session: 5m]  │
├────────────────────────────────────────────────────────────────────┤
│  [Coach] [Live]                                                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  🎤 REAL-TIME CONVERSATION                                 │    │
│  │  ─────────────────────────────────────────────────────────  │    │
│  │                                                            │    │
│  │  ┌──────────────────────────────────────────────────────┐  │    │
│  │  │ 👤 Entrevistador                                     │  │    │
│  │  │ "Can you walk me through your experience with       │  │    │
│  │  │  team leadership?"                                   │  │    │
│  │  │ ─────────────────────────────────────────            │  │    │
│  │  │ 10:45:12 • Duration: 8s                      [LIVE] │  │    │
│  │  └──────────────────────────────────────────────────────┘  │    │
│  │                                                            │    │
│  │  ┌──────────────────────────────────────────────────────┐  │    │
│  │  │ 🎤 Tú (candidato)                                     │  │    │
│  │  │ "Sure! In my previous role as a tech lead..."       │  │    │
│  │  │ ─────────────────────────────────────────            │  │    │
│  │  │ 10:45:20 • Duration: 15s                            │  │    │
│  │  └──────────────────────────────────────────────────────┘  │    │
│  │                                                            │    │
│  │  ┌──────────────────────────────────────────────────────┐  │    │
│  │  │ 💡 Coach                                             │  │    │
│  │  │ "Consider quantifying your leadership impact..."     │  │    │
│  │  │ ─────────────────────────────────────────            │  │    │
│  │  │ [View Full Suggestion]  Quality: 78%                │  │    │
│  │  └──────────────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  [⏹ End Session]  [◉ Pause]  [🔊 Audio: On]  [⚙ Settings]   │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 8. Consideraciones de Accesibilidad

### 8.1 WCAG 2.1 AA Compliance

| Requisito | Implementación |
|-----------|----------------|
| Contraste 4.5:1 (texto normal) | Todos los colores de texto cumplen |
| Contraste 3:1 (texto grande) | Headers y labels |
| Contraste 3:1 (UI components) | Bordes, iconos, indicadores |
| Focus visible | Anillo de focus `ring-2 ring-accent` |
| Etiquetas ARIA | Todos los componentes interactivos |
| Screen reader | Roles apropiados (region, status, log) |
| Keyboard navigation | Tab order logical, skip links |

### 8.2 Modo Alto Contraste (Opcional)

```css
/* CSS custom properties para modo alto contraste */
.high-contrast {
  --bg-primary: #000000;
  --bg-secondary: #1a1a1a;
  --text-primary: #ffffff;
  --text-secondary: #e0e0e0;
  --accent: #00d4ff;
  --border: #ffffff;
  
  /* Aumentar grosor de bordes */
  --border-width: 2px;
  
  /* Eliminar sombras, usar bordes */
  --shadow-sm: none;
  --shadow-md: none;
}
```

### 8.3 Clases de Accesibilidad

```jsx
// Skip link para navegación por teclado
<a href="#main-content" className="
  absolute -top-10 left-0
  bg-accent text-white
  px-4 py-2
  focus:top-0
  z-50
">
  Skip to main content
</a>

// Indicadores de estado con ARIA
<div
  role="status"
  aria-live="polite"
  aria-label="Connection status"
  className="sr-only"
>
  Connected to server
</div>

// Focus visible mejorado
button:focus-visible {
  outline: none;
  ring-2 ring-accent ring-offset-2 ring-offset-background;
}
```

---

## 9. Implementación en Tailwind CSS

### 9.1 Configuración Recomendada

```javascript
// tailwind.config.js completo
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  darkMode: 'class', // Usar clase .dark para modo oscuro
  theme: {
    extend: {
      colors: {
        // Colors palette
        interview: {
          bg: {
            primary: '#0a0f1a',
            secondary: '#111827',
            tertiary: '#1e293b',
            surface: '#1e293b',
          },
          text: {
            primary: '#f1f5f9',
            secondary: '#94a3b8',
            muted: '#64748b',
          },
          accent: {
            DEFAULT: '#0ea5e9',
            hover: '#38bdf8',
          },
          caption: {
            bg: '#0f172a',
            border: '#0ea5e9',
            text: '#f8fafc',
            partial: '#94a3b8',
            indicator: '#22c55e',
          },
          history: {
            card: '#111827',
            border: '#1e293b',
            interviewer: '#1e293b',
            candidate: '#0f172a',
            coach: '#1e1b4b',
          },
          status: {
            listening: '#0ea5e9',
            processing: '#f59e0b',
            idle: '#64748b',
            success: '#22c55e',
            error: '#ef4444',
          }
        }
      },
      fontSize: {
        'caption-lg': ['1.25rem', { lineHeight: '1.6' }],
        'caption': ['1rem', { lineHeight: '1.6' }],
        'overline': ['0.6875rem', { lineHeight: '1.3', letterSpacing: '0.08em' }],
      },
      boxShadow: {
        'glow-blue': '0 0 20px rgba(14, 165, 233, 0.3)',
        'glow-purple': '0 0 20px rgba(139, 92, 246, 0.3)',
        'card': '0 4px 6px rgba(0, 0, 0, 0.3)',
        'card-lg': '0 10px 15px rgba(0, 0, 0, 0.3)',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'sound-wave': 'sound-wave 1s ease-in-out infinite',
      },
      keyframes: {
        'sound-wave': {
          '0%, 100%': { height: '40%' },
          '50%': { height: '100%' },
        }
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
    require('@tailwindcss/aspect-ratio'),
  ],
}
```

### 9.2 Componentes Base Reutilizables

```tsx
// components/ui/CaptionCard.tsx
interface CaptionCardProps {
  transcript: string;
  isPartial?: boolean;
  timestamp?: string;
}

export function CaptionCard({ transcript, isPartial = false, timestamp }: CaptionCardProps) {
  return (
    <div className="
      bg-interview-caption-bg
      border border-interview-caption-border
      rounded-lg
      overflow-hidden
      shadow-card
    ">
      <div className="
        flex items-center justify-between
        px-4 py-3
        border-b border-interview-caption-border
        bg-interview-bg-secondary
      ">
        <div className="flex items-center gap-2">
          <span className="
            w-2 h-2 rounded-full
            bg-interview-status-listening
            animate-pulse
          " />
          <span className="
            text-overline
            font-semibold
            tracking-wider
            uppercase
            text-interview-accent
          ">
            Live Caption
          </span>
        </div>
        {timestamp && (
          <span className="font-mono text-xs text-interview-text-muted">
            {timestamp}
          </span>
        )}
      </div>

      <div className="p-4">
        <p className={`
          text-interview-caption-text
          text-caption-lg
          leading-relaxed
          ${isPartial ? 'italic text-interview-caption-partial' : ''}
        `}>
          {transcript}
        </p>
      </div>
    </div>
  );
}
```

```tsx
// components/ui/ConversationMessage.tsx
interface MessageProps {
  speaker: 'interviewer' | 'candidate' | 'coach';
  content: string;
  timestamp: string;
  duration?: string;
}

export function ConversationMessage({ speaker, content, timestamp, duration }: MessageProps) {
  const styles = {
    interviewer: {
      container: 'bg-interview-history-interviewer border-l-4 border-slate-500',
      avatar: 'bg-slate-500',
      icon: '👤',
      label: 'Entrevistador'
    },
    candidate: {
      container: 'bg-interview-history-candidate border-l-4 border-interview-accent',
      avatar: 'bg-interview-accent',
      icon: '🎤',
      label: 'Tú (candidato)'
    },
    coach: {
      container: 'bg-gradient-to-br from-interview-history-coach to-interview-bg-primary border-l-4 border-purple-500',
      avatar: 'bg-gradient-to-br from-purple-500 to-interview-accent',
      icon: '💡',
      label: 'Coach'
    }
  };

  const style = styles[speaker];

  return (
    <div className={`rounded-xl p-4 ${style.container}`}>
      <div className="flex items-start gap-3">
        <div className={`
          w-8 h-8 rounded-full
          flex items-center justify-center
          ${style.avatar}
          text-white text-sm
        `}>
          {style.icon}
        </div>
        
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm font-semibold text-interview-text-primary">
              {style.label}
            </span>
            {speaker === 'interviewer' && (
              <span className="
                px-2 py-0.5 rounded text-xs
                bg-slate-500/20 text-slate-400
              ">
                LIVE
              </span>
            )}
          </div>
          
          <p className="text-base leading-relaxed text-interview-text-primary">
            {content}
          </p>
          
          <div className="
            flex items-center gap-3 mt-2
            text-xs text-interview-text-muted font-mono
          ">
            <span>{timestamp}</span>
            {duration && <span>Duration: {duration}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

## 10. Checklist de Implementación Priorizada

### Fase 1: Fundamentos (Prioridad Alta)

- [ ] Actualizar `tailwind.config.js` con la nueva paleta de colores
- [ ] Crear componentes base: `CaptionCard`, `ConversationMessage`
- [ ] Implementar indicadores de estado (Connection, Listening, Processing)
- [ ] Agregar animaciones CSS para estados en tiempo real

### Fase 2: Componentes Principales (Prioridad Alta)

- [ ] Rediseñar Live Captions con nuevo layout
- [ ] Rediseñar Conversation History con distinción de turnos
- [ ] Rediseñar Coach Suggestions con mejor jerarquía visual
- [ ] Implementar Real-Time Conversation view

### Fase 3: Optimización UX (Prioridad Media)

- [ ] Agregar transiciones suaves entre estados
- [ ] Implementar auto-scroll inteligente para captions
- [ ] Agregar keyboard shortcuts
- [ ] Optimizar performance de scroll en historial

### Fase 4: Accesibilidad (Prioridad Media)

- [ ] Agregar skip links
- [ ] Mejorar ARIA labels
- [ ] Implementar modo alto contraste
- [ ] Testing con screen readers

### Fase 5: polish (Prioridad Baja)

- [ ] Micro-interacciones en hover states
- [ ] Animaciones de entrada para nuevos elementos
- [ ] Feedback visual para acciones del usuario
- [ ] Responsive en tablets y dispositivos móviles

---

## 11. Notas de Implementación Gradual

### Compatibilidad con Arquitectura Existente

Este diseño **no modifica** la arquitectura de componentes existente. Se integra mediante:

1. **Nuevos componentes UI** en `components/ui/` que usan la nueva paleta
2. **Props adicionales** en componentes existentes para soportar nuevos estilos
3. **CSS custom properties** que no rompen estilos actuales
4. **Wrapper components** que mantienen API existente

### Preservación de Reglas HR

- **HR-1 (Live Caption)**: El diseño mantiene Live Caption como servicio independiente visual
- **HR-2 (Conversation History)**: El diseño refuerza la separación y acceso al historial
- **HR-3 (Rollback)**: Los cambios son incrementales y reversibles
- **HR-4 (Manual Coach)**: El diseño no coupling el botón manual con estados de sesión

### Recursos Necesarios para Implementación

- Tiempo estimado por fase: 2-4 horas
- Testing requerido: Visual regression, accessibility audit
- Dependencias adicionales: `@tailwindcss/typography`, `@tailwindcss/forms`
