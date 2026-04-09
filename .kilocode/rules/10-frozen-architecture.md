# Frozen Architecture Rule

The following are frozen unless explicitly approved:
- Tauri desktop is the canonical shipped UI
- Next.js root web preview is non-canonical
- Full response is the primary visible artifact
- Bullets are preview/support only
- Deepgram remains the STT provider
- PostgreSQL + pgvector remain the persistence backbone
- No architecture redesign

Do not introduce parallel implementations.
Do not treat the old web preview as the product.
