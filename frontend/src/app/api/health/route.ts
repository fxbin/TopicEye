import { NextResponse } from 'next/server';

/**
 * Frontend liveness probe.  It intentionally avoids the `/api/*` backend
 * rewrite so a temporary API delay cannot mark the Next.js container down.
 */
export function GET() {
  return NextResponse.json({ status: 'ok' });
}
