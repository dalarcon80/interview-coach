"""
Interview Coach - FastAPI Server
WebSocket-based real-time coaching server
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import core components
from contracts.models import (
    SessionState, Exchange, InterviewConfig, UserProfile,
    GeneratedResponse, QuestionAnalysis, LanguageDecision,
)
from pipeline.realtime_pipeline import RealtimePipeline
from adapters.provider_registry import get_registry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
active_sessions: dict[str, RealtimePipeline] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    logger.info("🚀 Interview Coach Core starting...")
    # Initialize provider registry
    registry = get_registry()
    logger.info(f"Provider registry loaded: {registry}")
    yield
    logger.info("👋 Interview Coach Core shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Interview Coach Core",
    description="Real-time AI interview coaching backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================
# REST API Endpoints
# =====================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(active_sessions),
        "version": "1.0.0",
    }


class SessionCreate(BaseModel):
    """Request to create a new session"""
    company_name: str
    role_title: str
    job_description: Optional[str] = None
    company_values: list[str] = []
    response_style: str = "mixed"
    language_preference: str = "auto"
    user_name: str = "Candidate"
    resume_text: Optional[str] = None
    achievements: list[str] = []


@app.post("/api/sessions")
async def create_session(request: SessionCreate):
    """Create a new interview session"""
    import uuid
    
    session_id = str(uuid.uuid4())
    
    config = InterviewConfig(
        company_name=request.company_name,
        role_title=request.role_title,
        job_description=request.job_description,
        company_values=request.company_values,
        response_style=request.response_style,
        language_preference=request.language_preference,
    )
    
    profile = UserProfile(
        name=request.user_name,
        resume_text=request.resume_text,
        achievements=request.achievements,
    )
    
    # Create mock adapters for demo
    from adapters.mock_adapters import MockLLMAdapter, MockEmbeddingAdapter
    
    pipeline = RealtimePipeline(
        llm_adapter=MockLLMAdapter(),
        embedding_adapter=MockEmbeddingAdapter(),
        config=config,
        profile=profile,
    )
    
    active_sessions[session_id] = pipeline
    
    return {
        "session_id": session_id,
        "status": "created",
        "config": config.model_dump(),
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session state"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    pipeline = active_sessions[session_id]
    return pipeline.state.model_dump()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    if session_id in active_sessions:
        del active_sessions[session_id]
    return {"status": "deleted"}


# =====================
# WebSocket Endpoint
# =====================

class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket connected for session: {session_id}")
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        logger.info(f"WebSocket disconnected for session: {session_id}")
    
    async def send_json(self, session_id: str, data: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(data)


manager = ConnectionManager()


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time coaching.
    
    Message types:
    - partial_transcript: Partial transcription (while interviewer speaks)
    - final_transcript: Final transcription (turn ended)
    - user_response: User's actual response (for tracking)
    """
    if session_id not in active_sessions:
        await websocket.close(code=4004, reason="Session not found")
        return
    
    pipeline = active_sessions[session_id]
    await manager.connect(session_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "partial_transcript":
                # Handle partial - do speculative work
                text = data.get("text", "")
                await pipeline.on_partial_transcript(text)
                
                await manager.send_json(session_id, {
                    "type": "speculative_update",
                    "intent": pipeline._speculative_intent,
                })
            
            elif message_type == "final_transcript":
                # Handle final - full pipeline
                text = data.get("text", "")
                language = data.get("language")
                
                # Notify processing started
                await manager.send_json(session_id, {
                    "type": "processing_started",
                    "timestamp": datetime.now().isoformat(),
                })
                
                # Run pipeline
                exchange = await pipeline.on_final_transcript(text, language)
                
                # Send bullets first
                await manager.send_json(session_id, {
                    "type": "bullets_ready",
                    "bullets": exchange.suggested_response.bullets,
                    "timestamp": datetime.now().isoformat(),
                })
                
                # Then send full response
                await manager.send_json(session_id, {
                    "type": "response_ready",
                    "exchange": exchange.model_dump(),
                    "timestamp": datetime.now().isoformat(),
                })
            
            elif message_type == "user_response":
                # Track what user actually said
                text = data.get("text", "")
                exchange_index = data.get("exchange_index", len(pipeline.state.exchanges) - 1)
                
                if 0 <= exchange_index < len(pipeline.state.exchanges):
                    pipeline.state.exchanges[exchange_index].user_actual_response = text
                    warnings = pipeline.tracker.update_from_user_response(
                        text, 
                        pipeline.state.exchanges[exchange_index].analysis
                    )
                    
                    if warnings:
                        await manager.send_json(session_id, {
                            "type": "warnings",
                            "warnings": warnings,
                        })
            
            elif message_type == "ping":
                await manager.send_json(session_id, {"type": "pong"})
    
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(session_id)


# =====================
# Demo/Testing Endpoint
# =====================

@app.post("/api/demo/process")
async def demo_process(
    question: str,
    company: str = "TechCorp",
    role: str = "Senior Engineer",
    language: str = "es",
):
    """
    Demo endpoint to test the pipeline without WebSocket.
    Processes a single question and returns the response.
    """
    import uuid
    
    session_id = str(uuid.uuid4())
    
    config = InterviewConfig(
        company_name=company,
        role_title=role,
        language_preference=language,
    )
    
    profile = UserProfile(
        name="Demo Candidate",
        achievements=[
            "Led a team of 5 engineers",
            "Reduced deployment time by 60%",
            "Implemented CI/CD pipeline",
        ],
        resume_text="Senior software engineer with 8 years of experience in distributed systems.",
    )
    
    from adapters.mock_adapters import MockLLMAdapter, MockEmbeddingAdapter
    
    pipeline = RealtimePipeline(
        llm_adapter=MockLLMAdapter(),
        embedding_adapter=MockEmbeddingAdapter(),
        config=config,
        profile=profile,
    )
    
    exchange = await pipeline.on_final_transcript(question)
    
    return {
        "session_id": session_id,
        "question": question,
        "bullets": exchange.suggested_response.bullets,
        "full_response": exchange.suggested_response.full_response,
        "analysis": exchange.analysis.model_dump() if exchange.analysis else None,
        "quality": exchange.quality.model_dump() if exchange.quality else None,
        "latency_ms": exchange.latency_ms,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
