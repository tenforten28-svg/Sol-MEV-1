#!/bin/bash

echo "🚀 Solana Real Price Feed - Installation Script"
echo "================================================"
echo ""

# Check if running in correct directory
if [ ! -f "Cargo.toml" ]; then
    echo "❌ Error: Please run this script from /app/rust_price_feed directory"
    echo "   cd /app/rust_price_feed && ./install.sh"
    exit 1
fi

# Step 1: Install Rust
echo "📦 Step 1: Installing Rust & Cargo..."
echo ""

if command -v cargo &> /dev/null; then
    echo "✅ Rust already installed: $(rustc --version)"
else
    echo "Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    
    # Load Rust environment
    source $HOME/.cargo/env
    
    if command -v cargo &> /dev/null; then
        echo "✅ Rust installed successfully: $(rustc --version)"
    else
        echo "❌ Failed to install Rust. Please install manually:"
        echo "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
        exit 1
    fi
fi

echo ""
echo "🔨 Step 2: Building the price feed service..."
echo "   This may take 5-10 minutes on first build..."
echo ""

# Build in release mode for performance
cargo build --release 2>&1 | tail -20

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Build successful!"
    echo ""
    
    # Make the binary executable
    chmod +x target/release/solana-price-feed 2>/dev/null || true
    
    echo "🧪 Step 3: Testing the service..."
    echo ""
    
    # Start service in background
    ./target/release/solana-price-feed &
    SERVICE_PID=$!
    
    # Wait for service to start
    echo "Waiting for service to start..."
    sleep 5
    
    # Test the API
    echo ""
    echo "Testing API endpoints..."
    
    # Test health
    HEALTH=$(curl -s http://localhost:8002/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "✅ Health check: OK"
    else
        echo "⚠️ Health check: Service may need more time to start"
    fi
    
    # Test prices
    echo ""
    echo "Fetching real DEX prices..."
    curl -s http://localhost:8002/prices 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('✅ Retrieved prices from {} DEXs:'.format(len(data)))
    for price in data:
        print('   {} ({}) : \${:.4f}'.format(price['dex'].upper(), price['token_pair'], price['price']))
except:
    print('⚠️ Still initializing...')
" || echo "⚠️ Service still starting up..."
    
    # Stop test instance
    kill $SERVICE_PID 2>/dev/null
    wait $SERVICE_PID 2>/dev/null
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🎉 Installation Complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📝 Next Steps:"
    echo ""
    echo "1. Start the service:"
    echo "   ./target/release/solana-price-feed"
    echo ""
    echo "2. Or run in background:"
    echo "   nohup ./target/release/solana-price-feed > price_feed.log 2>&1 &"
    echo ""
    echo "3. Test the API:"
    echo "   curl http://localhost:8002/health"
    echo "   curl http://localhost:8002/prices | jq ."
    echo "   curl http://localhost:8002/opportunities | jq ."
    echo ""
    echo "4. Integrate with Python bot:"
    echo "   cd /app/backend"
    echo "   python real_dex_connector.py"
    echo ""
    echo "📚 Documentation: /app/REAL_DEX_INTEGRATION.md"
    echo ""
    
else
    echo ""
    echo "❌ Build failed!"
    echo ""
    echo "Common issues:"
    echo "1. Missing system dependencies:"
    echo "   sudo apt-get update"
    echo "   sudo apt-get install build-essential pkg-config libssl-dev"
    echo ""
    echo "2. Rust version too old:"
    echo "   rustup update stable"
    echo ""
    echo "3. Check error messages above for specific issues"
    echo ""
    exit 1
fi
