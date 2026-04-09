import { NextRequest, NextResponse } from 'next/server'

// Response templates by question type
const RESPONSE_TEMPLATES = {
  behavioral: {
    bullets: [
      '• Prepara tu respuesta usando el método STAR',
      '• Menciona una situación específica relevante al rol',
      '• Describe la acción concreta que tomaste',
      '• Cierra con el resultado cuantificable',
    ],
    full: 'En mi experiencia previa, enfrenté un desafío similar cuando [SITUACIÓN]. Mi responsabilidad era [TAREA]. Decidí [ACCIÓN] lo que resultó en [RESULTADO con métrica]. Esta experiencia me preparó perfectamente para los desafíos de este rol.',
  },
  technical: {
    bullets: [
      '• Describe el problema técnico específico',
      '• Explica los trade-offs considerados',
      '• Detalla la solución implementada',
      '• Menciona herramientas y tecnologías usadas',
    ],
    full: 'El desafío técnico era [PROBLEMA]. Evalué diferentes opciones: [OPCIÓN A] vs [OPCIÓN B]. Elegí [SOLUCIÓN] porque [RAZÓN]. Implementé usando [HERRAMIENTAS] y el resultado fue [OUTCOME con métrica].',
  },
  situational: {
    bullets: [
      '• Analiza el escenario planteado',
      '• Considera múltiples stakeholders',
      '• Propón una solución balanceada',
      '• Anticipa posibles objeciones',
    ],
    full: 'En ese escenario, primero identificaría [STAKEHOLDER PRINCIPAL]. Mi enfoque sería [APROACH] considerando [FACTORES]. Anticiparía [RIESGO] y prepararía [MITIGACIÓN].',
  },
}

// Question type detection
function detectQuestionType(question: string): string {
  const lowerQ = question.toLowerCase()
  
  const patterns: Record<string, string[]> = {
    behavioral: [
      'cuéntame', 'háblame', 'dime sobre', 'comparte',
      'tell me about', 'describe a time', 'give me an example',
      'experiencia', 'experience', 'situación', 'situation',
    ],
    technical: [
      'cómo', 'how would', 'implementar', 'implement',
      'arquitectura', 'architecture', 'diseñar', 'design',
      'sistema', 'system', 'código', 'code', 'tecnología',
    ],
    situational: [
      'qué harías', 'what would you do', 'si',
      'hipotética', 'hypothetical', 'imaginemos',
    ],
  }
  
  for (const [type, keywords] of Object.entries(patterns)) {
    if (keywords.some(kw => lowerQ.includes(kw))) {
      return type
    }
  }
  
  return 'behavioral'
}

// Detect language
function detectLanguage(text: string): string {
  const spanishIndicators = ['qué', 'cómo', 'cuál', 'por qué', 'cuéntame', 'experiencia', 'sobre', 'cuando']
  const lowerText = text.toLowerCase()
  
  const esCount = spanishIndicators.filter(w => lowerText.includes(w)).length
  
  return esCount >= 2 ? 'es' : 'en'
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { question, company, role, language, style } = body
    
    if (!question) {
      return NextResponse.json(
        { error: 'Question is required' },
        { status: 400 }
      )
    }
    
    const startTime = Date.now()
    
    // Detect question type and language
    const questionType = detectQuestionType(question)
    const detectedLanguage = language === 'auto' ? detectLanguage(question) : language
    
    // Get template based on question type
    const template = RESPONSE_TEMPLATES[questionType as keyof typeof RESPONSE_TEMPLATES] || RESPONSE_TEMPLATES.behavioral
    
    // Generate response
    const bullets = template.bullets
    const fullResponse = template.full
    
    // Simulate processing latency
    await new Promise(resolve => setTimeout(resolve, 500))
    
    const latency = Date.now() - startTime
    
    return NextResponse.json({
      session_id: `demo-${Date.now()}`,
      question,
      bullets,
      full_response: fullResponse,
      analysis: {
        primary_type: questionType,
        is_compound: question.includes(' y ') || question.includes(' and '),
        key_topics: ['experiencia', 'resultados', 'metodología'],
        recommended_style: style || 'mixed',
      },
      quality: {
        passed: true,
        score: 0.85,
        issues: [],
      },
      latency_ms: latency,
      language_detected: detectedLanguage,
    })
  } catch (error) {
    console.error('Process error:', error)
    return NextResponse.json(
      { error: 'Failed to process question' },
      { status: 500 }
    )
  }
}
