/**
 * Interview Coach - Suggest API Route
 * 
 * Proxy to backend coaching API on port 8000.
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
 * POST /api/coach/suggest
 * Generate interview response suggestion
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { 
      questionText, 
      style = 'mixed', 
      candidate, 
      company,
      cvFullText,
      roleRequirements,
      provider,
      model
    } = body;

    if (!questionText) {
      return NextResponse.json({ 
        success: false, 
        error: 'Pregunta requerida' 
      }, { status: 400 });
    }

    // Forward to backend API
    const response = await fetch(BACKEND.suggest, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        questionText,
        style,
        candidate,
        company,
        cvFullText,
        roleRequirements,
        provider,
        model
      })
    });

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
    console.error('Suggest API error:', error);
    
    // Fallback: Try internal SDK if backend unavailable
    if (error instanceof Error && error.message.includes('fetch')) {
      return NextResponse.json(
        { 
          success: false, 
          error: 'Backend service unavailable. Please ensure the coaching API is running on port 8000.' 
        },
        { status: 503 }
      );
    }
    
    const message = error instanceof Error ? error.message : 'Error al generar sugerencia';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
