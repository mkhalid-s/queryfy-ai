#!/bin/bash
# ==========================================
# QueryfyAI - SSL Certificate Generator
# ==========================================
# Generates self-signed SSL certificates
#
# Usage:
#   ./scripts/generate-certs.sh                    # Generate with defaults
#   ./scripts/generate-certs.sh mydomain.local     # Custom domain
# ==========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CERT_DIR="$PROJECT_DIR/nginx/ssl"
DOMAIN="${1:-queryfyai.local}"
DAYS="${2:-365}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# Create certificate directory
mkdir -p "$CERT_DIR"

log "Generating self-signed SSL certificate..."
log "Domain: $DOMAIN"
log "Validity: $DAYS days"
log "Output: $CERT_DIR"

# Generate private key and certificate
openssl req -x509 -nodes -days "$DAYS" -newkey rsa:2048 \
    -keyout "$CERT_DIR/queryfyai.key" \
    -out "$CERT_DIR/queryfyai.crt" \
    -subj "/CN=$DOMAIN/O=QueryfyAI/C=US" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

# Set permissions
chmod 600 "$CERT_DIR/queryfyai.key"
chmod 644 "$CERT_DIR/queryfyai.crt"

log "Certificates generated successfully!"
echo ""
echo "Files created:"
echo "  - $CERT_DIR/queryfyai.crt (certificate)"
echo "  - $CERT_DIR/queryfyai.key (private key)"
echo ""
echo "Certificate details:"
openssl x509 -in "$CERT_DIR/queryfyai.crt" -noout -subject -dates
echo ""

warn "This is a self-signed certificate."
warn "Clients will need to trust this certificate or disable verification."
echo ""
echo "To use with Docker:"
echo "  1. Mount the ssl directory: -v ./nginx/ssl:/etc/nginx/ssl:ro"
echo "  2. Include ssl.conf in your nginx configuration"
echo ""
echo "To trust on macOS:"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERT_DIR/queryfyai.crt"
echo ""
echo "To trust on Linux:"
echo "  sudo cp $CERT_DIR/queryfyai.crt /usr/local/share/ca-certificates/"
echo "  sudo update-ca-certificates"
