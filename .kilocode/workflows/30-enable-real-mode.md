# Enable Real Mode Workflow

Use this when the local machine can finally validate what remote environments could not.

1. Start Docker if needed
2. Run `docker compose up -d`
3. Validate backend health
4. Ensure required API keys are present in environment
5. Switch retrieval/composer/CV paths from demo to real where configured
6. Re-run targeted tests
7. Update status and README truthfully
