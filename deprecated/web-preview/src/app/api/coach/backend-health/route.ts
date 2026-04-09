/**
 * Backend Health Check Route
 * Proxies to Python FastAPI backend on port 8000
 */

import { NextResponse } from 'next/server';
import { BACKEND } from '@/lib/backend-config';

export async function GET() {
  try {
    const response = await fetch(BACKEND.health, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return NextResponse.json({
        status: 'unhealthy',
        timestamp: new Date().toISOString(),
        db_connected: false,
        version: 'unknown',
        providers_loaded: false,
      }, { status: 503 });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({
      status: 'offline',
      timestamp: new Date().toISOString(),
      db_connected: false,
      version: 'unknown',
      providers_loaded: false,
      error: 'Python backend not responding. Start with: cd python-core && python main.py',
    }, { status: 503 });
  }
}
