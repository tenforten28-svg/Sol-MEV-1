#!/bin/bash

# Solana Real Price Feed Setup Script

echo "🚀 Setting up Solana Real DEX Price Feed Service"
echo "================================================"

# Check if Rust is installed
if ! command -v cargo &> /dev/null; then
    echo "❌ Rust is not installed!"
    echo "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
fi

echo "✅ Rust version: $(rustc --version)"

# Navigate to rust project
cd /app/rust_price_feed

# Build the project
echo ""
echo "🔨 Building Rust price feed service..."
cargo build --release

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    
    # Create systemd service file
    echo ""
    echo "📝 Creating systemd service..."
    
    sudo tee /etc/systemd/system/solana-price-feed.service > /dev/null <<EOF
[Unit]
Description=Solana Real DEX Price Feed Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/app/rust_price_feed
ExecStart=/app/rust_price_feed/target/release/solana-price-feed
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd and start service
    sudo systemctl daemon-reload
    sudo systemctl enable solana-price-feed
    sudo systemctl start solana-price-feed
    
    echo "✅ Service created and started!"
    echo ""
    echo "📊 Service Status:"
    sudo systemctl status solana-price-feed --no-pager
    
    echo ""
    echo "🎉 Setup complete!"
    echo ""
    echo "Commands:"
    echo "  - Check status: sudo systemctl status solana-price-feed"
    echo "  - View logs:    sudo journalctl -u solana-price-feed -f"
    echo "  - Restart:      sudo systemctl restart solana-price-feed"
    echo "  - Stop:         sudo systemctl stop solana-price-feed"
    echo ""
    echo "API Endpoints:"
    echo "  - Health:        http://localhost:8002/health"
    echo "  - Prices:        http://localhost:8002/prices"
    echo "  - Opportunities: http://localhost:8002/opportunities"
    echo ""
    
    # Test the API
    echo "🧪 Testing API..."
    sleep 5
    curl http://localhost:8002/health
    echo ""
    
else
    echo "❌ Build failed! Check the error messages above."
    exit 1
fi
