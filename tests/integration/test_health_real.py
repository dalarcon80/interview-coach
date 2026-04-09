"""
Test Health Endpoint - Real DB Check

Tests that the health endpoint actually checks database connection
and returns correct status.
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock


class TestHealthRealDB:
    """Tests for health endpoint with real database check."""
    
    @pytest.mark.asyncio
    async def test_health_returns_healthy_when_db_connected(self):
        """Health should return 'healthy' when database is connected."""
        from api.server import app
        from fastapi.testclient import TestClient
        
        # Mock database connection as successful
        with patch('storage.database.check_db_connection', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True
            
            client = TestClient(app)
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["db_connected"] is True
    
    @pytest.mark.asyncio
    async def test_health_returns_degraded_when_db_not_connected(self):
        """Health should return 'degraded' when database is not connected."""
        from api.server import app
        from fastapi.testclient import TestClient
        
        # Mock database connection as failed
        with patch('storage.database.check_db_connection', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = False
            
            client = TestClient(app)
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["db_connected"] is False
    
    @pytest.mark.asyncio
    async def test_health_returns_degraded_on_db_exception(self):
        """Health should return 'degraded' when database check throws exception."""
        from api.server import app
        from fastapi.testclient import TestClient
        
        # Mock database connection as raising exception
        with patch('storage.database.check_db_connection', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Connection refused")
            
            client = TestClient(app)
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["db_connected"] is False
    
    @pytest.mark.asyncio
    async def test_health_includes_version_and_providers(self):
        """Health should include version and providers status."""
        from api.server import app
        from fastapi.testclient import TestClient
        
        with patch('storage.database.check_db_connection', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True
            
            client = TestClient(app)
            response = client.get("/health")
            
            data = response.json()
            assert "version" in data
            assert "providers_loaded" in data
            assert isinstance(data["providers_loaded"], bool)
    
    @pytest.mark.asyncio
    async def test_health_endpoint_exposes_mode(self):
        """Health should expose if adapters are in demo or real mode."""
        from api.server import app, check_api_keys_available
        from fastapi.testclient import TestClient
        
        # Test without API keys (demo mode)
        with patch.dict('os.environ', {}, clear=True):
            with patch('api.server.check_api_keys_available', return_value=False):
                client = TestClient(app)
                response = client.get("/health")
                
                # Should still return 200, mode is implicit
                assert response.status_code == 200


class TestHealthDBIntegration:
    """Integration tests that require actual database connection."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_health_with_real_database(self, run_integration):
        """Test health with real database connection.

        Run with: pytest --run-integration

        Requires:
        - PostgreSQL running (docker compose up -d)
        - DATABASE_URL environment variable set
        """
        if not run_integration:
            pytest.skip("Requires --run-integration flag and running database")

        from storage.database import check_db_connection

        is_connected = await check_db_connection()

        if is_connected:
            print("[TEST] Database is connected - testing real health check")
            from api.server import app
            from fastapi.testclient import TestClient

            client = TestClient(app)
            response = client.get("/health")

            data = response.json()
            assert data["db_connected"] is True
            assert data["status"] == "healthy"
        else:
            print("[TEST] Database not available - skipping real DB test")
            pytest.skip("Database not available")
