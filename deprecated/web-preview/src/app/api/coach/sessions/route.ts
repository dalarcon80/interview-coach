/**
 * Interview Coach - Sessions API Route
 * 
 * Proxy to backend session management.
 * Uses file-based session store for persistence.
 * 
 * Architecture compliance:
 * - Sessions persist across server restarts
 * - No in-memory Maps that lose data
 * - Backend handles all session logic
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  createSession,
  getSession,
  updateSession,
  deleteSession,
  listSessions,
  addExchange,
  exportSession,
  importSession,
  type InterviewSession
} from '@/lib/session-store';

/**
 * POST /api/coach/sessions
 * Create a new interview session
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { 
      company_name, 
      role_title, 
      job_description,
      response_style, 
      language_preference 
    } = body;

    const session = createSession({
      companyName: company_name || 'TechCorp',
      roleTitle: role_title || 'Senior Engineer',
      jobDescription: job_description,
      responseStyle: response_style || 'mixed',
      languagePreference: language_preference || 'auto'
    });

    return NextResponse.json({
      success: true,
      session_id: session.id,
      status: 'created',
      config: {
        company_name: session.companyName,
        role_title: session.roleTitle,
        response_style: session.responseStyle,
        language_preference: session.languagePreference
      }
    });
  } catch (error) {
    console.error('Session creation error:', error);
    return NextResponse.json(
      { success: false, error: 'Failed to create session' },
      { status: 500 }
    );
  }
}

/**
 * GET /api/coach/sessions
 * Get session by ID or list all sessions
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const sessionId = searchParams.get('session_id');
    const action = searchParams.get('action');

    // Export session
    if (action === 'export' && sessionId) {
      const json = exportSession(sessionId);
      if (!json) {
        return NextResponse.json(
          { success: false, error: 'Session not found' },
          { status: 404 }
        );
      }
      return new NextResponse(json, {
        headers: {
          'Content-Type': 'application/json',
          'Content-Disposition': `attachment; filename="session-${sessionId}.json"`
        }
      });
    }

    // Get specific session
    if (sessionId) {
      const session = getSession(sessionId);
      if (!session) {
        return NextResponse.json(
          { success: false, error: 'Session not found' },
          { status: 404 }
        );
      }
      return NextResponse.json({ success: true, session });
    }

    // List all sessions
    const sessions = listSessions();
    return NextResponse.json({ success: true, sessions });
  } catch (error) {
    console.error('Session get error:', error);
    return NextResponse.json(
      { success: false, error: 'Failed to get session(s)' },
      { status: 500 }
    );
  }
}

/**
 * PUT /api/coach/sessions
 * Update session or add exchange
 */
export async function PUT(request: NextRequest) {
  try {
    const body = await request.json();
    const { session_id, updates, exchange } = body;

    if (!session_id) {
      return NextResponse.json(
        { success: false, error: 'session_id required' },
        { status: 400 }
      );
    }

    // Add exchange to session
    if (exchange) {
      const newExchange = addExchange(session_id, exchange);
      if (!newExchange) {
        return NextResponse.json(
          { success: false, error: 'Session not found' },
          { status: 404 }
        );
      }
      return NextResponse.json({ success: true, exchange: newExchange });
    }

    // Update session
    const session = updateSession(session_id, updates);
    if (!session) {
      return NextResponse.json(
        { success: false, error: 'Session not found' },
        { status: 404 }
      );
    }

    return NextResponse.json({ success: true, session });
  } catch (error) {
    console.error('Session update error:', error);
    return NextResponse.json(
      { success: false, error: 'Failed to update session' },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/coach/sessions
 * Delete a session
 */
export async function DELETE(request: NextRequest) {
  try {
    const body = await request.json();
    const { session_id } = body;

    if (!session_id) {
      return NextResponse.json(
        { success: false, error: 'session_id required' },
        { status: 400 }
      );
    }

    const deleted = deleteSession(session_id);
    return NextResponse.json({ success: deleted });
  } catch (error) {
    console.error('Session delete error:', error);
    return NextResponse.json(
      { success: false, error: 'Failed to delete session' },
      { status: 500 }
    );
  }
}
