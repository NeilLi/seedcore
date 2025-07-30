#!/bin/bash

# Script to set up PUBLIC_GRAFANA_URL environment variable
# This fixes the 404 errors in Ray dashboard Grafana iframes

echo "Setting up PUBLIC_GRAFANA_URL for Ray dashboard..."

# Get the public IP address (AWS metadata service)
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")

echo "Detected public IP: $PUBLIC_IP"

# Set the environment variable
export PUBLIC_GRAFANA_URL="http://$PUBLIC_IP:3000"

echo "PUBLIC_GRAFANA_URL set to: $PUBLIC_GRAFANA_URL"
echo "Note: This IP will be added to your .env file for local use only."
echo "For production, consider using a domain name instead of IP address."

# Create .env file if it doesn't exist
if [ ! -f "../.env" ]; then
    echo "Creating .env file..."
    cp ../env.example ../.env
fi

# Add or update PUBLIC_GRAFANA_URL in .env file
if grep -q "PUBLIC_GRAFANA_URL" ../.env; then
    # Update existing line
    sed -i "s|PUBLIC_GRAFANA_URL=.*|PUBLIC_GRAFANA_URL=$PUBLIC_GRAFANA_URL|" ../.env
    echo "Updated PUBLIC_GRAFANA_URL in .env file"
else
    # Add new line
    echo "" >> ../.env
    echo "# Ray Dashboard Grafana URL" >> ../.env
    echo "PUBLIC_GRAFANA_URL=$PUBLIC_GRAFANA_URL" >> ../.env
    echo "Added PUBLIC_GRAFANA_URL to .env file"
fi

echo ""
echo "Setup complete! To apply changes:"
echo "1. Restart your Ray cluster:"
echo "   docker compose down"
echo "   docker compose up -d"
echo "2. If using Ray workers:"
echo "   docker compose -f ray-workers.yml -p seedcore down"
echo "   docker compose -f ray-workers.yml -p seedcore up -d"
echo ""
echo "The Ray dashboard should now properly display Grafana metrics without 404 errors." 