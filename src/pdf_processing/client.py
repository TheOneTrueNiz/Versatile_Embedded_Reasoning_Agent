#!/usr/bin/env python3
"""
PDF Processing Client for VERA
===============================

HTTP client for the pdf-document-layout-analysis microservice.
Provides async methods for all PDF analysis endpoints.

Usage:
    client = PDFClient()

    # Analyze PDF layout
    segments = await client.analyze_pdf("document.pdf")

    # Extract text
    text = await client.extract_text("document.pdf", types=["title", "text"])

    # Convert to markdown
    markdown = await client.to_markdown("document.pdf")
"""

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# Try httpx first (preferred), fall back to optional aiohttp
_httpx = None
_aiohttp = None

try:
    import httpx
    _httpx = httpx
except ImportError:
    try:
        import aiohttp
        _aiohttp = aiohttp
    except ImportError:
        pass  # Will be caught when creating client


@dataclass
class PDFServiceConfig:
    """Configuration for PDF service connection."""
    host: str = "localhost"
    port: int = 5060
    timeout_seconds: int = 300  # 5 minutes for large PDFs
    use_gpu: bool = True

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class PDFSegment:
    """A segment extracted from a PDF page."""
    left: float
    top: float
    width: float
    height: float
    page_number: int
    page_width: float
    page_height: float
    text: str
    segment_type: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PDFSegment":
        return cls(
            left=data.get("left", 0),
            top=data.get("top", 0),
            width=data.get("width", 0),
            height=data.get("height", 0),
            page_number=data.get("page_number", 1),
            page_width=data.get("page_width", 0),
            page_height=data.get("page_height", 0),
            text=data.get("text", ""),
            segment_type=data.get("type", "Text")
        )


@dataclass
class TOCItem:
    """Table of contents item."""
    title: str
    level: int
    page_number: int
    indentation: Optional[int] = None


@dataclass
class PDFAnalysisResult:
    """Result of PDF analysis."""
    success: bool
    file_path: str
    segments: List[PDFSegment] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def get_by_type(self, segment_type: str) -> List[PDFSegment]:
        """Get segments by type."""
        return [s for s in self.segments if s.segment_type.lower() == segment_type.lower()]

    def get_text(self, types: Optional[List[str]] = None) -> str:
        """Get combined text from segments."""
        if types:
            segments = [s for s in self.segments if s.segment_type.lower() in [t.lower() for t in types]]
        else:
            segments = self.segments
        return "\n\n".join(s.text for s in segments if s.text)


class PDFClient:
    """
    Async HTTP client for pdf-document-layout-analysis service.

    Provides methods for:
    - PDF layout analysis
    - Text extraction
    - OCR processing
    - TOC extraction
    - Format conversion (Markdown, HTML)
    - Visualization

    Uses httpx for async HTTP requests, with aiohttp as fallback.
    """

    def __init__(self, config: Optional[PDFServiceConfig] = None):
        """
        Initialize PDF client.

        Args:
            config: Service configuration (uses defaults if None)
        """
        if _httpx is None and _aiohttp is None:
            raise ImportError(
                "Either httpx or aiohttp is required for PDF client. "
                "Install with: pip install httpx"
            )

        self.config = config or PDFServiceConfig()
        self._client: Optional[Any] = None
        self._use_httpx = _httpx is not None

    async def _get_client(self):
        """Get or create HTTP client."""
        if self._client is None:
            if self._use_httpx:
                self._client = _httpx.AsyncClient(timeout=self.config.timeout_seconds)
            else:
                timeout = _aiohttp.ClientTimeout(total=self.config.timeout_seconds)
                self._client = _aiohttp.ClientSession(timeout=timeout)
        return self._client

    async def close(self):
        """Close the client session."""
        if self._client:
            if self._use_httpx:
                await self._client.aclose()
            else:
                if not self._client.closed:
                    await self._client.close()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def is_available(self) -> bool:
        """Check if PDF service is available."""
        try:
            client = await self._get_client()
            if self._use_httpx:
                response = await client.get(f"{self.config.base_url}/")
                return response.status_code == 200
            else:
                async with client.get(f"{self.config.base_url}/") as response:
                    return response.status == 200
        except Exception as e:
            logger.debug(f"PDF service not available: {e}")
            return False

    async def get_info(self) -> Dict[str, Any]:
        """Get service information."""
        client = await self._get_client()
        if self._use_httpx:
            response = await client.get(f"{self.config.base_url}/info")
            if response.status_code == 200:
                return response.json()
            raise RuntimeError(f"Failed to get service info: {response.status_code}")
        else:
            async with client.get(f"{self.config.base_url}/info") as response:
                if response.status == 200:
                    return await response.json()
                raise RuntimeError(f"Failed to get service info: {response.status}")

    async def _post_file(
        self,
        endpoint: str,
        file_path: Path,
        form_fields: Dict[str, str]
    ) -> tuple:
        """
        Helper to POST a file with form data.

        Returns:
            Tuple of (status_code, response_data_or_bytes, content_type)
        """
        client = await self._get_client()

        if self._use_httpx:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path.name, f, 'application/pdf')}
                response = await client.post(
                    f"{self.config.base_url}{endpoint}",
                    files=files,
                    data=form_fields
                )
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    return response.status_code, response.json(), content_type
                else:
                    return response.status_code, response.content, content_type
        else:
            data = _aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=file_path.name)
            for key, value in form_fields.items():
                data.add_field(key, value)

            async with client.post(f"{self.config.base_url}{endpoint}", data=data) as response:
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    return response.status, await response.json(), content_type
                else:
                    return response.status, await response.read(), content_type

    async def analyze_pdf(
        self,
        file_path: Union[str, Path],
        fast: bool = False,
        parse_tables_and_math: bool = False
    ) -> PDFAnalysisResult:
        """
        Analyze PDF layout and extract segments.

        Args:
            file_path: Path to PDF file
            fast: Use fast LightGBM model instead of VGT
            parse_tables_and_math: Extract tables as HTML, formulas as LaTeX

        Returns:
            PDFAnalysisResult with segments
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return PDFAnalysisResult(
                success=False,
                file_path=str(file_path),
                error=f"File not found: {file_path}"
            )

        try:
            status, data, _ = await self._post_file(
                "/",
                file_path,
                {
                    'fast': str(fast).lower(),
                    'parse_tables_and_math': str(parse_tables_and_math).lower()
                }
            )

            if status == 200:
                segments = [PDFSegment.from_dict(s) for s in data]
                return PDFAnalysisResult(
                    success=True,
                    file_path=str(file_path),
                    segments=segments
                )
            else:
                return PDFAnalysisResult(
                    success=False,
                    file_path=str(file_path),
                    error=f"Analysis failed: {data}"
                )
        except Exception as e:
            return PDFAnalysisResult(
                success=False,
                file_path=str(file_path),
                error=str(e)
            )

    async def extract_text(
        self,
        file_path: Union[str, Path],
        types: Optional[List[str]] = None,
        fast: bool = False
    ) -> Dict[str, Any]:
        """
        Extract text from PDF by content types.

        Args:
            file_path: Path to PDF file
            types: Content types to extract (e.g., ["title", "text", "table"])
            fast: Use fast model

        Returns:
            Dict with extracted text
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            status, data, _ = await self._post_file(
                "/text",
                file_path,
                {
                    'fast': str(fast).lower(),
                    'types': ",".join(types) if types else "all"
                }
            )

            if status == 200:
                return {"success": True, "text": data}
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def extract_toc(
        self,
        file_path: Union[str, Path],
        fast: bool = False
    ) -> Dict[str, Any]:
        """
        Extract table of contents from PDF.

        Args:
            file_path: Path to PDF file
            fast: Use fast model

        Returns:
            Dict with TOC items
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            status, data, _ = await self._post_file(
                "/toc",
                file_path,
                {'fast': str(fast).lower()}
            )

            if status == 200:
                return {"success": True, "toc": data}
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def ocr_pdf(
        self,
        file_path: Union[str, Path],
        language: str = "en",
        output_path: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Apply OCR to scanned PDF.

        Args:
            file_path: Path to PDF file
            language: OCR language code (e.g., "en", "fr", "de")
            output_path: Path to save OCR'd PDF (None = temp file)

        Returns:
            Dict with OCR result and output path
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            status, data, _ = await self._post_file(
                "/ocr",
                file_path,
                {'language': language}
            )

            if status == 200:
                # OCR returns a PDF file as bytes
                if output_path:
                    output_path = Path(output_path)
                else:
                    output_path = file_path.with_suffix('.ocr.pdf')

                output_path.write_bytes(data)
                return {
                    "success": True,
                    "output_path": str(output_path),
                    "language": language
                }
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def to_markdown(
        self,
        file_path: Union[str, Path],
        fast: bool = False,
        extract_toc: bool = False,
        dpi: int = 120,
        output_file: Optional[str] = None,
        target_languages: Optional[List[str]] = None,
        translation_model: str = "gpt-oss"
    ) -> Dict[str, Any]:
        """
        Convert PDF to Markdown.

        Args:
            file_path: Path to PDF file
            fast: Use fast model
            extract_toc: Include table of contents
            dpi: Image resolution
            output_file: Output filename (triggers zip response)
            target_languages: Languages for translation
            translation_model: Ollama model for translation

        Returns:
            Dict with markdown content or zip path
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            form_fields = {
                'fast': str(fast).lower(),
                'extract_toc': str(extract_toc).lower(),
                'dpi': str(dpi)
            }
            if output_file:
                form_fields['output_file'] = output_file
            if target_languages:
                form_fields['target_languages'] = ",".join(target_languages)
            if translation_model:
                form_fields['translation_model'] = translation_model

            status, data, content_type = await self._post_file(
                "/markdown",
                file_path,
                form_fields
            )

            if status == 200:
                if 'application/zip' in content_type or output_file:
                    # Zip response (binary data)
                    zip_path = file_path.with_suffix('.md.zip')
                    zip_path.write_bytes(data)
                    return {
                        "success": True,
                        "format": "zip",
                        "output_path": str(zip_path)
                    }
                else:
                    # Direct markdown response
                    content = data.decode('utf-8') if isinstance(data, bytes) else str(data)
                    return {
                        "success": True,
                        "format": "markdown",
                        "content": content
                    }
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def to_html(
        self,
        file_path: Union[str, Path],
        fast: bool = False,
        extract_toc: bool = False,
        dpi: int = 120,
        output_file: Optional[str] = None,
        target_languages: Optional[List[str]] = None,
        translation_model: str = "gpt-oss"
    ) -> Dict[str, Any]:
        """
        Convert PDF to HTML.

        Args:
            file_path: Path to PDF file
            fast: Use fast model
            extract_toc: Include table of contents
            dpi: Image resolution
            output_file: Output filename (triggers zip response)
            target_languages: Languages for translation
            translation_model: Ollama model for translation

        Returns:
            Dict with HTML content or zip path
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            form_fields = {
                'fast': str(fast).lower(),
                'extract_toc': str(extract_toc).lower(),
                'dpi': str(dpi)
            }
            if output_file:
                form_fields['output_file'] = output_file
            if target_languages:
                form_fields['target_languages'] = ",".join(target_languages)
            if translation_model:
                form_fields['translation_model'] = translation_model

            status, data, content_type = await self._post_file(
                "/html",
                file_path,
                form_fields
            )

            if status == 200:
                if 'application/zip' in content_type or output_file:
                    zip_path = file_path.with_suffix('.html.zip')
                    zip_path.write_bytes(data)
                    return {
                        "success": True,
                        "format": "zip",
                        "output_path": str(zip_path)
                    }
                else:
                    content = data.decode('utf-8') if isinstance(data, bytes) else str(data)
                    return {
                        "success": True,
                        "format": "html",
                        "content": content
                    }
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def visualize(
        self,
        file_path: Union[str, Path],
        fast: bool = False,
        output_path: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Generate visualization of PDF segmentation.

        Args:
            file_path: Path to PDF file
            fast: Use fast model
            output_path: Path to save visualization PDF

        Returns:
            Dict with visualization result
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            status, data, _ = await self._post_file(
                "/visualize",
                file_path,
                {'fast': str(fast).lower()}
            )

            if status == 200:
                if output_path:
                    output_path = Path(output_path)
                else:
                    output_path = file_path.with_suffix('.viz.pdf')

                output_path.write_bytes(data)
                return {
                    "success": True,
                    "output_path": str(output_path)
                }
            else:
                return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_pdf_client():
        """Test PDF client (requires running PDF service)."""
        print("Testing PDF Client...")
        print("=" * 50)

        # Test 1: Create client
        print("Test 1: Create client...", end=" ")
        client = PDFClient()
        print("PASS")

        # Test 2: Check availability
        print("Test 2: Check service availability...", end=" ")
        available = await client.is_available()
        if available:
            print("PASS (service running)")
        else:
            print("SKIP (service not running)")
            print("\n" + "=" * 50)
            print("PDF service not available. Start it with:")
            print("  docker compose up -d")
            print("  # or: make start")
            await client.close()
            return True

        # Test 3: Get info
        print("Test 3: Get service info...", end=" ")
        info = await client.get_info()
        assert "sys" in info
        print("PASS")

        # Test 4: Cleanup
        await client.close()
        print("Test 4: Cleanup...", end=" ")
        print("PASS")

        print("\n" + "=" * 50)
        print("All tests passed!")
        return True

    success = asyncio.run(test_pdf_client())
    sys.exit(0 if success else 1)
