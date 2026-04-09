/**
 * Interview Coach - Analyze CV API Route
 * 
 * Proxy to backend CV analysis service.
 * All LLM logic and model IDs are handled by the backend.
 * 
 * Architecture compliance:
 * - No model IDs in frontend code
 * - No LLM logic in frontend routes
 * - Backend handles all provider configuration
 */

import { NextRequest, NextResponse } from 'next/server';
import { BACKEND } from '@/lib/backend-config';

/**
 * POST /api/coach/analyze-cv
 * Analyze CV and extract structured profile
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { cvText, provider, model } = body;

    if (!cvText || !cvText.trim()) {
      return NextResponse.json(
        { success: false, error: 'Se requiere el texto del CV' },
        { status: 400 }
      );
    }

    // Forward to backend API
    const response = await fetch(BACKEND.analyzeCV, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        cvText,
        provider,
        model
      })
    });

    // Handle 501 Not Implemented
    if (response.status === 501) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { 
          success: false, 
          error: 'CV analysis requires LLM API key',
          detail: errorData.detail || { message: 'Configure ANTHROPIC_API_KEY or OPENAI_API_KEY' }
        },
        { status: 501 }
      );
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Backend error' }));
      return NextResponse.json(
        { success: false, error: error.error || `Backend error: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error: unknown) {
    console.error('CV analysis error:', error);
    
    if (error instanceof Error && error.message.includes('fetch')) {
      return NextResponse.json(
        { 
          success: false, 
          error: 'Backend service unavailable. Please ensure the coaching API is running on port 8000.' 
        },
        { status: 503 }
      );
    }
    
    const message = error instanceof Error ? error.message : 'Error al analizar el CV';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
