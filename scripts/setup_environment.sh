#!/bin/bash
################################################################################
# VERA Environment Setup Script
# ==============================
#
# Sets up Python environment for VERA with all dependencies.
#
# Usage:
#   ./setup_environment.sh [venv|conda]
#
# Options:
#   venv   - Use Python venv (default)
#   conda  - Use conda environment
################################################################################

set -e  # Exit on error

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}VERA Environment Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

ENV_TYPE="${1:-venv}"

cd "$(dirname "$0")"

# Check Python version
echo -e "${BLUE}Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version | awk '{print $2}')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    echo -e "${YELLOW}⚠️  Python 3.8+ recommended, found $PYTHON_VERSION${NC}"
else
    echo -e "${GREEN}✅ Python $PYTHON_VERSION${NC}"
fi

# Setup based on type
if [ "$ENV_TYPE" = "conda" ]; then
    echo
    echo -e "${BLUE}Setting up conda environment...${NC}"

    # Check if conda is available
    if ! command -v conda &> /dev/null; then
        echo -e "${YELLOW}❌ conda not found. Please install Miniconda or Anaconda.${NC}"
        exit 1
    fi

    # Create conda environment
    ENV_NAME="vera"
    echo "Creating conda environment: $ENV_NAME"
    conda create -n $ENV_NAME python=3.11 -y

    echo
    echo -e "${GREEN}✅ Conda environment created${NC}"
    echo
    echo "To activate:"
    echo "  conda activate $ENV_NAME"
    echo
    echo "Then install dependencies:"
    echo "  pip install -r requirements.txt"

else
    echo
    echo -e "${BLUE}Setting up Python venv...${NC}"

    # Create venv
    if [ -d "venv" ]; then
        echo -e "${YELLOW}venv/ directory already exists${NC}"
        read -p "Recreate? (y/n): " response
        if [ "$response" = "y" ]; then
            rm -rf venv
        else
            echo "Using existing venv"
        fi
    fi

    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo -e "${GREEN}✅ Virtual environment created${NC}"
    fi

    # Activate and install dependencies
    echo
    echo -e "${BLUE}Installing dependencies...${NC}"
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

    echo
    echo -e "${GREEN}✅ Dependencies installed${NC}"
    echo
    echo "To activate:"
    echo "  source venv/bin/activate"
fi

echo
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Setup Complete${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo "Next steps:"
echo "  1. Set your xAI API key:"
echo "     export XAI_API_KEY='your-api-key'"
echo
echo "  2. Run VERA:"
echo "     python src/run_vera.py"
echo
echo "  3. Or run tests:"
echo "     ./test_vera_interactive.sh"
echo
