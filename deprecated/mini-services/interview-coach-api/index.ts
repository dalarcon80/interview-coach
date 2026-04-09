/**
 * Interview Coach API Service
 * Port: 8001
 * 
 * Provides LLM integration for interview coaching.
 * Supports: OpenAI, Claude (requires user API keys)
 * 
 * Architecture compliance:
 * - No hardcoded model IDs (uses providers.yaml aliases)
 * - All coaching logic in backend
 * - Frontend is UI shell only
 */

import { serve } from "bun";

// ============================================
// In-memory API Key Storage (server-side only)
// ============================================
const apiKeys: Map<string, string> = new Map();

// Provider configurations from providers.yaml
const PROVIDER_CONFIG = {
  llm: {
    main: {
      alias: "llm_main",
      provider: "anthropic",
      model: "claude-sonnet-4-20250514",
    },
    fast: {
      alias: "llm_fast", 
      provider: "anthropic",
      model: "claude-haiku-4-5-20251001",
    }
  }
};

// Environment overrides
function getModelAlias(alias: string): string {
  const envOverride = process.env[`PROVIDER_LLM_${alias.toUpperCase()}_MODEL`];
  return envOverride || PROVIDER_CONFIG.llm[alias === 'llm_main' ? 'main' : 'fast']?.model || '';
}

// ============================================
// Style Guides
// ============================================
const STYLE_GUIDES: Record<string, string> = {
  executive: `
ESTILO EXECUTIVE (C-Level):
- Respuesta MUY concisa (100-150 palabras máximo)
- Enfócate en métricas, resultados, ROI
- Lenguaje directo sin rodeos
- Estructura: Contexto → Acción → Resultado cuantificado
- Tono: Seguro, estratégico, de alto nivel`,
  commercial: `
ESTILO COMMERCIAL (Persuasivo):
- Respuesta persuasiva (150-200 palabras)
- Enfatiza valor y beneficios para la empresa
- Conecta tus logros con las necesidades del rol
- Estructura: Problema → Tu solución → Beneficio tangible
- Tono: Entusiasta pero profesional, orientado a resultados`,
  technical: `
ESTILO TECHNICAL (Detallado):
- Respuesta detallada (200-300 palabras)
- Incluye arquitectura, tecnologías, metodologías
- Detalla implementación y lecciones aprendidas
- Estructura: Contexto técnico → Enfoque → Resultados medibles
- Tono: Profesional, preciso, con terminología apropiada`,
  mixed: `
ESTILO MIXTO (Balanceado):
- Respuesta balanceada (150-250 palabras)
- Combina estrategia con implementación
- Usa metodología STAR (Situación, Tarea, Acción, Resultado)
- Balance entre visión de negocio y detalles técnicos
- Tono: Profesional y adaptable`
};

// ============================================
// LLM Provider Functions
// ============================================

async function callOpenAI(apiKey: string, model: string, systemPrompt: string, userPrompt: string): Promise<string> {
  const res = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt }
      ],
      temperature: 0.7,
      max_tokens: 1500
    })
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error?.message || `OpenAI Error: ${res.status}`);
  }

  const data = await res.json();
  return data.choices[0]?.message?.content || '';
}

async function callClaude(apiKey: string, model: string, systemPrompt: string, userPrompt: string): Promise<string> {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01'
    },
    body: JSON.stringify({
      model,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
      max_tokens: 1500
    })
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error?.message || `Claude Error: ${res.status}`);
  }

  const data = await res.json();
  return data.content[0]?.text || '';
}

// ============================================
// API Key Masking
// ============================================
function maskKey(key: string): string {
  if (key.length <= 8) return '***';
  return key.substring(0, 4) + '...' + key.substring(key.length - 4);
}

// ============================================
// HTTP Server
// ============================================

const server = serve({
  port: 8001,
  
  async fetch(req) {
    const url = new URL(req.url);
    const path = url.pathname;
    const method = req.method;

    // CORS headers
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle preflight
    if (method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // =====================
      // Health Check
      // =====================
      if (path === '/health' && method === 'GET') {
        return Response.json({ 
          status: 'healthy', 
          service: 'interview-coach-api',
          port: 8001,
          timestamp: new Date().toISOString(),
          providers: ['openai', 'claude']
        }, { headers: corsHeaders });
      }

      // =====================
      // Config Endpoints
      // =====================
      if (path === '/api/config') {
        if (method === 'GET') {
          // Return masked API keys status
          const config: Record<string, { configured: boolean; masked?: string }> = {};
          ['openai', 'claude'].forEach(provider => {
            const key = apiKeys.get(provider);
            config[provider] = {
              configured: !!key,
              masked: key ? maskKey(key) : undefined
            };
          });
          return Response.json({ success: true, config }, { headers: corsHeaders });
        }
        
        if (method === 'POST') {
          const body = await req.json();
          const { provider, apiKey } = body;
          
          if (!provider || !apiKey) {
            return Response.json({ 
              success: false, 
              error: 'provider and apiKey required' 
            }, { status: 400, headers: corsHeaders });
          }
          
          apiKeys.set(provider, apiKey);
          return Response.json({ 
            success: true, 
            masked: maskKey(apiKey) 
          }, { headers: corsHeaders });
        }
        
        if (method === 'DELETE') {
          const body = await req.json();
          const { provider } = body;
          apiKeys.delete(provider);
          return Response.json({ success: true }, { headers: corsHeaders });
        }
      }

      // =====================
      // Test API Connection
      // =====================
      if (path === '/api/test' && method === 'POST') {
        const body = await req.json();
        const { provider, apiKey, model } = body;
        
        const testPrompt = 'Responde solo con: OK';
        
        try {
          let result: string;
          
          if (provider === 'openai') {
            const key = apiKey || apiKeys.get('openai');
            if (!key) throw new Error('OpenAI API key not configured. Please enter your API key in settings.');
            result = await callOpenAI(key, model || 'gpt-4o-mini', 'You are a helpful assistant. Respond briefly.', testPrompt);
          } else if (provider === 'claude') {
            const key = apiKey || apiKeys.get('claude');
            if (!key) throw new Error('Claude API key not configured. Please enter your API key in settings.');
            result = await callClaude(key, model || getModelAlias('llm_fast'), 'You are a helpful assistant. Respond briefly.', testPrompt);
          } else {
            throw new Error(`Unknown provider: ${provider}. Please select OpenAI or Claude.`);
          }
          
          return Response.json({ 
            success: true, 
            message: 'API connection successful',
            result: result.substring(0, 100) 
          }, { headers: corsHeaders });
        } catch (error) {
          return Response.json({ 
            success: false, 
            message: error instanceof Error ? error.message : 'Test failed' 
          }, { status: 500, headers: corsHeaders });
        }
      }

      // =====================
      // Suggest Response
      // =====================
      if (path === '/api/suggest' && method === 'POST') {
        const body = await req.json();
        const { 
          questionText, 
          style = 'mixed', 
          candidate, 
          company,
          cvFullText,
          roleRequirements,
          provider,
          apiKey,
          model
        } = body;

        if (!questionText) {
          return Response.json({ 
            success: false, 
            error: 'Pregunta requerida' 
          }, { status: 400, headers: corsHeaders });
        }

        // Check provider requirements
        if (!provider || provider === 'internal') {
          return Response.json({ 
            success: false, 
            error: 'Por favor, selecciona OpenAI o Claude y configura tu API key en el botón Config.' 
          }, { status: 400, headers: corsHeaders });
        }

        // Build context
        const candidateContext = `
=== PERFIL COMPLETO DEL CANDIDATO ===
Nombre: ${candidate?.name || 'No especificado'}
Cargo Actual: ${candidate?.currentRole || 'No especificado'}
Empresa Actual: ${candidate?.currentCompany || 'No especificado'}
Años de Experiencia: ${candidate?.yearsExperience || 0} años

HABILIDADES CLAVE:
${(candidate?.skills || []).map((s: string) => `• ${s}`).join('\n')}

LOGROS DESTACADOS (con métricas):
${(candidate?.achievements || []).map((a: string) => `• ${a}`).join('\n')}
${candidate?.summary ? `\nRESUMEN PROFESIONAL:\n${candidate.summary}` : ''}
`;

        const companyContext = `
=== EMPRESA Y ROL OBJETIVO ===
Empresa: ${company?.companyName || 'No especificado'}
Puesto: ${company?.positionTitle || 'No especificado'}
${roleRequirements ? `\nREQUISITOS DEL ROL:\n${roleRequirements}` : ''}
`;

        const cvContextSection = cvFullText ? `
=== CV COMPLETO DEL CANDIDATO (referencia completa) ===
${cvFullText}
` : '';

        const systemPrompt = `Eres un coach de entrevistas de ALTO NIVEL. Tu trabajo es ayudar al candidato a dar respuestas IMPACTANTES y PERSONALIZADAS.

${candidateContext}
${companyContext}
${cvContextSection}

${STYLE_GUIDES[style] || STYLE_GUIDES.mixed}

=== INSTRUCCIONES CRÍTICAS ===
1. USA LA INFORMACIÓN EXACTA del CV/perfil del candidato - NUNCA inventes datos
2. PERSONALIZA la respuesta para el ROL OBJETIVO en la EMPRESA OBJETIVO
3. Si hay requisitos del rol, CONECTA tus logros con esos requisitos
4. INCLUYE métricas y números ESPECÍFICOS del perfil del candidato
5. La respuesta debe sonar NATURAL, como si el candidato la dijera en primera persona
6. NUNCA uses placeholders como [X años] - usa los datos reales del perfil

Genera UNA respuesta directa y lista para usar.

Responde SOLO con JSON válido: {"suggestedAnswer": "texto completo de la respuesta en primera persona"}`;

        const userPrompt = `PREGUNTA DEL ENTREVISTADOR: "${questionText}"

Genera la mejor respuesta posible para este candidato.`;

        let responseText: string;
        
        // Use API key from request if provided, otherwise use stored key
        const openaiKey = apiKey || apiKeys.get('openai');
        const claudeKey = apiKey || apiKeys.get('claude');
        
        if (provider === 'openai') {
          if (!openaiKey) {
            return Response.json({ 
              success: false, 
              error: 'OpenAI API key not provided. Please enter your API key in settings.' 
            }, { status: 400, headers: corsHeaders });
          }
          // Use model from request or default from config
          const modelToUse = model || 'gpt-4o';
          responseText = await callOpenAI(openaiKey, modelToUse, systemPrompt, userPrompt);
        } else if (provider === 'claude') {
          if (!claudeKey) {
            return Response.json({ 
              success: false, 
              error: 'Claude API key not provided. Please enter your API key in settings.' 
            }, { status: 400, headers: corsHeaders });
          }
          // Use model alias resolution (no hardcoded IDs in code path)
          const modelToUse = model || getModelAlias('llm_main');
          responseText = await callClaude(claudeKey, modelToUse, systemPrompt, userPrompt);
        } else {
          return Response.json({ 
            success: false, 
            error: 'Proveedor no soportado. Por favor selecciona OpenAI o Claude.' 
          }, { status: 400, headers: corsHeaders });
        }

        // Parse response
        let suggestion;
        try {
          const match = responseText.match(/\{[\s\S]*\}/);
          suggestion = match ? JSON.parse(match[0]) : { suggestedAnswer: responseText };
        } catch {
          suggestion = { suggestedAnswer: responseText };
        }

        return Response.json({ success: true, suggestion }, { headers: corsHeaders });
      }

      // =====================
      // Analyze CV
      // =====================
      if (path === '/api/analyze-cv' && method === 'POST') {
        const body = await req.json();
        const { cvText, provider, apiKey, model } = body;

        if (!cvText) {
          return Response.json({ 
            success: false, 
            error: 'CV text required' 
          }, { status: 400, headers: corsHeaders });
        }

        // Check provider requirements
        if (!provider || provider === 'internal') {
          return Response.json({ 
            success: false, 
            error: 'Por favor, selecciona OpenAI o Claude y configura tu API key en el botón Config.' 
          }, { status: 400, headers: corsHeaders });
        }

        const systemPrompt = `Eres un experto en análisis de CVs y perfiles profesionales.
Analiza el siguiente CV y extrae la información estructurada.
Responde SOLO con JSON válido con la siguiente estructura:
{
  "name": "Nombre del candidato",
  "currentRole": "Cargo actual",
  "currentCompany": "Empresa actual",
  "yearsExperience": número,
  "skills": ["skill1", "skill2", ...],
  "achievements": ["logro1 con métrica", "logro2 con métrica", ...],
  "summary": "Resumen profesional en 2-3 oraciones"
}`;

        let responseText: string;
        
        // Use API key from request if provided, otherwise use stored key
        const openaiKey = apiKey || apiKeys.get('openai');
        const claudeKey = apiKey || apiKeys.get('claude');
        
        if (provider === 'openai') {
          if (!openaiKey) {
            return Response.json({ 
              success: false, 
              error: 'OpenAI API key not provided. Please enter your API key in settings.' 
            }, { status: 400, headers: corsHeaders });
          }
          const modelToUse = model || 'gpt-4o';
          responseText = await callOpenAI(openaiKey, modelToUse, systemPrompt, cvText);
        } else if (provider === 'claude') {
          if (!claudeKey) {
            return Response.json({ 
              success: false, 
              error: 'Claude API key not provided. Please enter your API key in settings.' 
            }, { status: 400, headers: corsHeaders });
          }
          const modelToUse = model || getModelAlias('llm_fast');
          responseText = await callClaude(claudeKey, modelToUse, systemPrompt, cvText);
        } else {
          return Response.json({ 
            success: false, 
            error: 'Proveedor no soportado. Por favor selecciona OpenAI o Claude.' 
          }, { status: 400, headers: corsHeaders });
        }

        let profile;
        try {
          const match = responseText.match(/\{[\s\S]*\}/);
          profile = match ? JSON.parse(match[0]) : { summary: responseText };
        } catch {
          profile = { summary: responseText };
        }

        return Response.json({ success: true, profile }, { headers: corsHeaders });
      }

      // 404 for unknown routes
      return Response.json({ 
        success: false, 
        error: 'Not found' 
      }, { status: 404, headers: corsHeaders });

    } catch (error) {
      console.error('API Error:', error);
      return Response.json({ 
        success: false, 
        error: error instanceof Error ? error.message : 'Internal server error' 
      }, { status: 500, headers: corsHeaders });
    }
  }
});

console.log(`🚀 Interview Coach API running on http://localhost:${server.port}`);
console.log(`   Health: http://localhost:${server.port}/health`);
console.log(`   Config: http://localhost:${server.port}/api/config`);
console.log(`   Suggest: http://localhost:${server.port}/api/suggest`);
console.log(`   Providers: OpenAI, Claude (requires user API keys)`);
