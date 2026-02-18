# MCP PDF Reader Server (Python + FastMCP)

A powerful Model Context Protocol (MCP) server built with FastMCP that provides comprehensive PDF processing capabilities including text extraction, image extraction, and OCR for reading text within images.

## Features

- **Text Extraction**: Extract text content from PDF pages
- **Image Extraction**: Extract all images from PDF files
- **OCR Capabilities**: Read text from images using Tesseract OCR
- **Comprehensive Analysis**: Get detailed PDF structure and metadata
- **Page Range Support**: Process specific page ranges
- **Multiple Languages**: OCR support for multiple languages

## Prerequisites

### System Dependencies

#### Tesseract OCR
You need to install Tesseract OCR on your system:

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
1. Download from: https://github.com/UB-Mannheim/tesseract/wiki
2. Install and add to PATH
3. Or use: `conda install -c conda-forge tesseract`

#### Additional Language Packs (Optional)
```bash
# For multiple languages
sudo apt install tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa
```

## Installation

### Quick Start with UV

1. **Install UV (if not already installed):**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. **Clone/Create the project:**
```bash
mkdir mcp-pdf-reader-server
cd mcp-pdf-reader-server
```

3. **Initialize and install with UV:**
```bash
# Copy the files (pdf_reader_server.py and pyproject.toml)
# Then install dependencies
uv sync
```

4. **Verify installation:**
```bash
uv run python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
```

### Alternative: Manual Setup

If you prefer traditional setup:

1. **Create virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install fastmcp PyMuPDF pytesseract Pillow
```

## Usage

### Running the Server

With UV:
```bash
uv run python pdf_reader_server.py
```

Or if you have the environment activated:
```bash
python pdf_reader_server.py
```

The server will start and listen for MCP requests on stdin/stdout.

### Available Tools

#### 1. `read_pdf_text`
Extract text content from PDF pages.

**Parameters:**
- `file_path` (string, required): Path to the PDF file
- `page_range` (object, optional): Dict with `start` and `end` page numbers

**Example:**
```json
{
  "file_path": "/path/to/document.pdf",
  "page_range": {"start": 1, "end": 5}
}
```

#### 2. `extract_pdf_images`
Extract all images from a PDF file.

**Parameters:**
- `file_path` (string, required): Path to the PDF file
- `output_dir` (string, optional): Directory to save images
- `page_range` (object, optional): Page range to process

**Example:**
```json
{
  "file_path": "/path/to/document.pdf",
  "output_dir": "/path/to/images/",
  "page_range": {"start": 1, "end": 3}
}
```

#### 3. `read_pdf_with_ocr`
Extract text from both regular text and images using OCR.

**Parameters:**
- `file_path` (string, required): Path to the PDF file
- `page_range` (object, optional): Page range to process
- `ocr_language` (string, optional): OCR language code (default: "eng")

**Example:**
```json
{
  "file_path": "/path/to/document.pdf",
  "ocr_language": "eng+fra",
  "page_range": {"start": 1, "end": 10}
}
```

**Supported OCR Languages:**
- `eng` - English
- `fra` - French
- `deu` - German
- `spa` - Spanish
- `eng+fra` - Multiple languages

#### 4. `get_pdf_info`
Get comprehensive metadata and statistics about a PDF.

**Parameters:**
- `file_path` (string, required): Path to the PDF file

#### 5. `analyze_pdf_structure`
Analyze the structure and content distribution of a PDF.

**Parameters:**
- `file_path` (string, required): Path to the PDF file

## Configuration with Claude Desktop

### With UV
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pdf-reader": {
      "command": "uv",
      "args": ["run", "python", "/path/to/your/pdf_reader_server.py"],
      "cwd": "/path/to/your/mcp-pdf-reader-server"
    }
  }
}
```

### With Virtual Environment
```json
{
  "mcpServers": {
    "pdf-reader": {
      "command": "/path/to/your/.venv/bin/python",
      "args": ["/path/to/your/pdf_reader_server.py"]
    }
  }
}
```

### System Python
```json
{
  "mcpServers": {
    "pdf-reader": {
      "command": "python",
      "args": ["/path/to/your/pdf_reader_server.py"],
      "env": {
        "PYTHONPATH": "/path/to/your/.venv/lib/python3.x/site-packages"
      }
    }
  }
}
```

## Example Responses

### Text Extraction Response
```json
{
  "success": true,
  "file_path": "/path/to/document.pdf",
  "pages_processed": "1-3",
  "total_pages": 10,
  "pages_text": [
    {
      "page_number": 1,
      "text": "Page 1 content...",
      "word_count": 125
    }
  ],
  "combined_text": "All text combined...",
  "total_word_count": 1250,
  "total_character_count": 8750
}
```

### OCR Response
```json
{
  "success": true,
  "file_path": "/path/to/document.pdf",
  "pages_processed": "1-2",
  "ocr_language": "eng",
  "pages_data": [
    {
      "page_number": 1,
      "text": "Regular text from PDF...",
      "ocr_text": "Text extracted from images...",
      "images_with_text": [
        {
          "image_index": 1,
          "ocr_text": "Text from image 1",
          "confidence": "high"
        }
      ],
      "combined_text": "Combined text and OCR...",
      "text_word_count": 100,
      "ocr_word_count": 25
    }
  ],
  "summary": {
    "total_text_word_count": 200,
    "total_ocr_word_count": 50,
    "combined_word_count": 250,
    "images_processed": 3
  },
  "all_text_combined": "All extracted text..."
}
```

## Performance Considerations

### OCR Performance
- OCR processing can be slow for large images
- Consider processing smaller page ranges for faster results
- Images smaller than 50x50 pixels are automatically skipped

### Memory Usage
- Large PDFs with many images may consume significant memory
- The server processes pages sequentially to manage memory usage
- Extracted images are saved to disk to reduce memory pressure

### Optimization Tips
1. **Use page ranges** for large documents
2. **Specify output directories** for image extraction to avoid temp file buildup
3. **Choose appropriate OCR languages** to improve accuracy and speed
4. **Preprocess images** if OCR quality is poor (consider adding OpenCV)

## Troubleshooting

### Common Issues

1. **Tesseract not found:**
   ```
   TesseractNotFoundError: tesseract is not installed
   ```
   - Install Tesseract OCR system package
   - Ensure it's in your PATH

2. **Permission errors:**
   - Ensure the Python process has read access to PDF files
   - Ensure write access to output directories

3. **Poor OCR results:**
   - Try different OCR language codes
   - Consider image preprocessing
   - Check if images are high enough resolution

4. **Memory errors:**
   - Process smaller page ranges
   - Close other applications
   - Consider increasing available RAM

### Debug Mode

Run with debug logging using UV:
```bash
PYTHONUNBUFFERED=1 uv run python pdf_reader_server.py
```

Or with regular Python:
```bash
PYTHONUNBUFFERED=1 python pdf_reader_server.py
```

### Testing OCR
Test Tesseract directly:
```bash
tesseract --list-langs
tesseract image.png output.txt
```

## Dependencies

- **fastmcp**: Modern MCP server framework
- **PyMuPDF**: Fast PDF processing and rendering
- **pytesseract**: Python wrapper for Tesseract OCR
- **Pillow**: Image processing library
- **tesseract-ocr**: System OCR engine

## Advanced Features

### Custom OCR Configuration
You can modify the OCR configuration in the code:
```python
ocr_text = pytesseract.image_to_string(
    pil_image, 
    lang=ocr_language,
    config='--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz '
)
```

### Image Preprocessing
For better OCR results, consider adding image preprocessing:
```python
# Add to requirements: opencv-python, numpy
import cv2
import numpy as np

# Preprocessing example
def preprocess_image(image):
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return Image.fromarray(thresh)
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

MIT License - see LICENSE file for details.