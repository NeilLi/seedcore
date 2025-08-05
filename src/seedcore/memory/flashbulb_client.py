import requests
import os
import logging

logger = logging.getLogger(__name__)

class FlashbulbClient:
    """A simple client for agents to log incidents via the central API."""
    def __init__(self):
        # The API service is reachable via its container name on the Docker network
        # Use environment variables to determine the correct endpoint
        api_host = os.getenv("API_HOST", "seedcore-api")
        api_port = os.getenv("API_PORT", "8002")
        self.base_url = f"http://{api_host}:{api_port}"
        logger.info(f"FlashbulbClient configured for API at {self.base_url}")

    def log_incident(self, event_data: dict, salience_score: float) -> bool:
        """Makes an HTTP POST request to the /mfb/incidents endpoint."""
        try:
            # Send event_data as JSON body and salience_score as query parameter
            response = requests.post(
                f"{self.base_url}/mfb/incidents",
                json=event_data,
                params={"salience_score": salience_score},
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully logged incident via API: {response.json().get('incident_id')}")
                return True
            else:
                logger.error(f"Failed to log incident. Status: {response.status_code}, Body: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request to log incident failed: {e}")
            return False 