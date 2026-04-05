#!/bin/bash
set -euo pipefail

# Build an offline deployment bundle for Beaconhill.
# Produces: dist/beaconhill-offline/ containing:
#   - Python wheel + all dependency wheels
#   - setup.sh script for the target machine
#
# Prerequisites on build machine:
#   - Python 3.12
#   - pip with wheel support
#   - Ollama with gemma4:26b already pulled
#
# The Ollama binary and model weights must be transferred separately
# (they're too large to bundle: ~15GB for the model alone).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUNDLE_DIR="$PROJECT_DIR/dist/beaconhill-offline"
PYTHON="${PYTHON:-/opt/homebrew/opt/python@3.12/libexec/bin/python3}"

echo "Building offline bundle..."

# Clean previous bundle
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/wheels"

# Build the project wheel
echo "Building project wheel..."
cd "$PROJECT_DIR"
"$PYTHON" -m pip wheel --no-deps -w "$BUNDLE_DIR/wheels" .

# Download all dependency wheels
echo "Downloading dependency wheels..."
"$PYTHON" -m pip wheel -w "$BUNDLE_DIR/wheels" .

# Create the setup script for the target machine
cat > "$BUNDLE_DIR/setup.sh" << 'SETUP_EOF'
#!/bin/bash
set -euo pipefail

echo "Beaconhill Offline Setup"
echo "========================"

# Check Python 3.12
PYTHON=""
for candidate in python3.12 /opt/homebrew/opt/python@3.12/libexec/bin/python3 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" --version 2>&1 | grep -oE '3\.[0-9]+')
        if [[ "$version" == "3.12" ]] || [[ "$version" == "3.13" ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.12+ not found. Install it first:"
    echo "  brew install python@3.12"
    exit 1
fi
echo "Using Python: $PYTHON ($($PYTHON --version))"

# Check Ollama
if ! command -v ollama &>/dev/null; then
    echo "ERROR: Ollama not found. Install it first:"
    echo "  brew install ollama"
    exit 1
fi
echo "Ollama found: $(ollama --version)"

# Check model
if ! ollama list | grep -q "gemma4:26b"; then
    echo "WARNING: gemma4:26b not found in Ollama."
    echo "  Copy the model weights or run: ollama pull gemma4:26b"
fi

# Create venv and install
INSTALL_DIR="${HOME}/.local/beaconhill"
echo "Installing to $INSTALL_DIR..."
"$PYTHON" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --no-index --find-links wheels/ beaconhill

# Create symlink
LINK="${HOME}/.local/bin/beaconhill"
mkdir -p "$(dirname "$LINK")"
ln -sf "$INSTALL_DIR/venv/bin/beaconhill" "$LINK"

echo ""
echo "Done! Run with:"
echo "  ~/.local/bin/beaconhill"
echo ""
echo "Or add ~/.local/bin to your PATH:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
SETUP_EOF

chmod +x "$BUNDLE_DIR/setup.sh"

# Summary
echo ""
echo "Bundle created: $BUNDLE_DIR"
echo "Contents:"
ls -lh "$BUNDLE_DIR/wheels/" | tail -n +2
echo ""
echo "To deploy:"
echo "  1. Copy $BUNDLE_DIR to target machine"
echo "  2. Ensure Ollama + gemma4:26b are available"
echo "  3. Run: cd beaconhill-offline && ./setup.sh"
