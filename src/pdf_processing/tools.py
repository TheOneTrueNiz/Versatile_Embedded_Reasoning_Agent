#!/usr/bin/env python3
"""
PDF Processing Tools for VERA
==============================

Provides tool definitions and handlers for PDF document processing.
Integrates with VERA's tool system for LLM-driven PDF operations.

Based on pdf-document-layout-analysis microservice.

Usage:
    from pdf_processing.tools import PDF_TOOLS, PDFToolBridge

    # Get tool definitions
    tools = PDF_TOOLS

    # Create bridge and execute
    bridge = PDFToolBridge()
    result = await bridge.execute_tool("pdf_analyze", {"file_path": "doc.pdf"})
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from .client import PDFClient, PDFServiceConfig

logger = logging.getLogger(__name__)


# === PDF Tool Definitions (OpenAI Function Calling Format) ===

PDF_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "pdf_analyze",
            "description": (
                "Analyze PDF layout and extract document segments (titles, paragraphs, tables, images, formulas). "
                "Use for: understanding document structure, extracting structured content, processing research papers. "
                "Returns: segment_count, list of segments with type/text/page. "
                "Tip: Use fast=true for quick analysis, false for accuracy. "
                "Set parse_tables_and_math=true to get tables as HTML and formulas as LaTeX. "
                "This is the foundation tool - use before other PDF tools to understand document structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file to analyze"
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast LightGBM model (true) vs accurate VGT model (false, default)"
                    },
                    "parse_tables_and_math": {
                        "type": "boolean",
                        "description": "Extract tables as HTML and math formulas as LaTeX (slower but richer output)"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_extract_text",
            "description": (
                "Extract text from PDF, optionally filtering by content type. "
                "Use for: getting readable text, extracting specific content types, text-only conversion. "
                "Returns: extracted text, optionally filtered by type. "
                "Tip: Use types=['title', 'text'] to skip tables/images. "
                "Content types: 'title', 'text', 'table', 'image', 'formula', 'footnote', 'header', 'footer'. "
                "Simpler than pdf_analyze when you just need the text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Content types to extract: 'title', 'text', 'table', 'image', 'formula', 'footnote'. Omit for all."
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast model (default: false)"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_extract_toc",
            "description": (
                "Extract table of contents (outline) from PDF. "
                "Use for: getting document structure, navigation, section overview. "
                "Returns: hierarchical list of headings with page numbers. "
                "Tip: Works best on well-structured PDFs with proper heading hierarchy. "
                "Useful for understanding document organization before deep extraction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast model (default: false)"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_ocr",
            "description": (
                "Apply OCR (Optical Character Recognition) to scanned PDF to extract text from images. "
                "Use for: processing scanned documents, image-based PDFs, handwritten content recognition. "
                "Returns: OCR'd PDF with searchable text layer, or extracted text. "
                "Tip: Use when pdf_extract_text returns no text (indicates scanned/image PDF). "
                "Supports multiple languages. Processing time depends on PDF size."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "language": {
                        "type": "string",
                        "description": "OCR language code: 'en' (English), 'fr' (French), 'de' (German), 'es' (Spanish), etc."
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to save OCR'd PDF with searchable text layer (optional)"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_to_markdown",
            "description": (
                "Convert PDF to Markdown format preserving structure. "
                "Use for: creating editable documents, content migration, AI-readable format. "
                "Returns: Markdown text with headers, lists, tables (as MD tables), and image placeholders. "
                "Tip: Best for text-heavy documents. Tables converted to Markdown table syntax. "
                "Use extract_toc=true to add navigation at the top. "
                "Long content is truncated in response - save to file for full document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast model (default: false)"
                    },
                    "extract_toc": {
                        "type": "boolean",
                        "description": "Include table of contents at the beginning (default: false)"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "Image resolution for embedded images (default: 120)"
                    },
                    "target_languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Translate to languages (e.g., ['Spanish', 'French']). Optional."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_to_html",
            "description": (
                "Convert PDF to HTML format preserving layout and styling. "
                "Use for: web publishing, rich formatting preservation, interactive documents. "
                "Returns: HTML with CSS styling, tables preserved as HTML tables. "
                "Tip: Better than Markdown for complex layouts with columns, styling, images. "
                "Use extract_toc=true for navigation sidebar. "
                "Long content is truncated in response - save to file for full document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast model (default: false)"
                    },
                    "extract_toc": {
                        "type": "boolean",
                        "description": "Include table of contents (default: false)"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "Image resolution (default: 120)"
                    },
                    "target_languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Translate to languages (e.g., ['Spanish']). Optional."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_visualize",
            "description": (
                "Generate visualization PDF showing how the document was segmented. "
                "Use for: debugging extraction issues, understanding document structure, quality verification. "
                "Returns: path to visualization PDF with colored bounding boxes around detected segments. "
                "Tip: Use this to verify pdf_analyze is correctly identifying document elements. "
                "Helpful for diagnosing poor extraction results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file"
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use fast model (default: false)"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to save visualization PDF. Defaults to input_visualized.pdf"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_service_status",
            "description": (
                "Check if the PDF processing service is running and available. "
                "Use for: verifying service health before PDF operations, troubleshooting. "
                "Returns: available (bool), service info (version, capabilities). "
                "Tip: Call this first if PDF operations fail. "
                "Service runs as Docker container - start with 'docker compose up -d' if not running."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


class PDFToolBridge:
    """
    Bridges PDF processing to VERA's tool system.

    Provides:
    - Tool execution with result tracking
    - Error handling and logging
    - Service availability checking
    - Execution history
    """

    def __init__(
        self,
        client: Optional[PDFClient] = None,
        config: Optional[PDFServiceConfig] = None
    ):
        """
        Initialize the PDF tool bridge.

        Args:
            client: PDFClient instance (created if None)
            config: Service configuration
        """
        self.client = client or PDFClient(config)
        self._tools = PDF_TOOLS.copy()
        self._custom_handlers: Dict[str, Callable] = {}
        self._history: List[Dict] = []

    @property
    def tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions for the LLM."""
        return self._tools

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a custom handler for a tool."""
        self._custom_handlers[tool_name] = handler

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a PDF tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Result dictionary with success, result, and error
        """
        logger.info(f"Executing PDF tool: {name} with {arguments}")

        call_record = {
            "tool": name,
            "arguments": arguments,
            "timestamp": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

        try:
            # Check for custom handler
            if name in self._custom_handlers:
                handler = self._custom_handlers[name]
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(**arguments)
                else:
                    result = handler(**arguments)
            else:
                result = await self._default_handler(name, arguments)

            call_record["result"] = result
            self._history.append(call_record)

            return result

        except Exception as e:
            logger.error(f"PDF tool error: {e}")
            call_record["error"] = str(e)
            self._history.append(call_record)

            return {
                "success": False,
                "error": str(e)
            }

    async def _default_handler(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Default handlers for PDF tools."""

        if name == "pdf_analyze":
            result = await self.client.analyze_pdf(
                file_path=arguments["file_path"],
                fast=arguments.get("fast", False),
                parse_tables_and_math=arguments.get("parse_tables_and_math", False)
            )
            return {
                "success": result.success,
                "file_path": result.file_path,
                "segment_count": result.segment_count,
                "segments": [
                    {
                        "type": s.segment_type,
                        "text": s.text[:200] + "..." if len(s.text) > 200 else s.text,
                        "page": s.page_number
                    }
                    for s in result.segments[:20]  # Limit for LLM context
                ],
                "error": result.error
            }

        elif name == "pdf_extract_text":
            return await self.client.extract_text(
                file_path=arguments["file_path"],
                types=arguments.get("types"),
                fast=arguments.get("fast", False)
            )

        elif name == "pdf_extract_toc":
            return await self.client.extract_toc(
                file_path=arguments["file_path"],
                fast=arguments.get("fast", False)
            )

        elif name == "pdf_ocr":
            return await self.client.ocr_pdf(
                file_path=arguments["file_path"],
                language=arguments.get("language", "en"),
                output_path=arguments.get("output_path")
            )

        elif name == "pdf_to_markdown":
            result = await self.client.to_markdown(
                file_path=arguments["file_path"],
                fast=arguments.get("fast", False),
                extract_toc=arguments.get("extract_toc", False),
                dpi=arguments.get("dpi", 120),
                target_languages=arguments.get("target_languages")
            )
            # Truncate content for LLM if too long
            if result.get("success") and result.get("format") == "markdown":
                content = result.get("content", "")
                if len(content) > 5000:
                    result["content"] = content[:5000] + "\n\n... (truncated)"
                    result["truncated"] = True
            return result

        elif name == "pdf_to_html":
            result = await self.client.to_html(
                file_path=arguments["file_path"],
                fast=arguments.get("fast", False),
                extract_toc=arguments.get("extract_toc", False),
                dpi=arguments.get("dpi", 120),
                target_languages=arguments.get("target_languages")
            )
            # Truncate content for LLM if too long
            if result.get("success") and result.get("format") == "html":
                content = result.get("content", "")
                if len(content) > 5000:
                    result["content"] = content[:5000] + "\n\n... (truncated)"
                    result["truncated"] = True
            return result

        elif name == "pdf_visualize":
            return await self.client.visualize(
                file_path=arguments["file_path"],
                fast=arguments.get("fast", False),
                output_path=arguments.get("output_path")
            )

        elif name == "pdf_service_status":
            available = await self.client.is_available()
            if available:
                info = await self.client.get_info()
                return {
                    "success": True,
                    "available": True,
                    "info": info
                }
            return {
                "success": True,
                "available": False,
                "message": "PDF service not running. Start with: docker compose up -d"
            }

        else:
            raise NotImplementedError(f"No handler for PDF tool: {name}")

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent tool execution history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get tool bridge statistics."""
        return {
            "total_tools": len(self._tools),
            "custom_handlers": len(self._custom_handlers),
            "executions_total": len(self._history),
            "service_config": {
                "host": self.client.config.host,
                "port": self.client.config.port
            }
        }

    async def close(self):
        """Close the client connection."""
        await self.client.close()


# === Factory Function ===

def create_pdf_bridge(
    host: str = "localhost",
    port: int = 5060
) -> PDFToolBridge:
    """
    Create a PDF tool bridge.

    Args:
        host: PDF service host
        port: PDF service port

    Returns:
        Configured PDFToolBridge
    """
    config = PDFServiceConfig(host=host, port=port)
    return PDFToolBridge(config=config)


# === Tool Registration Helper ===

def get_pdf_tool_executor(bridge: PDFToolBridge) -> Callable:
    """
    Get tool executor function for AsyncToolExecutor integration.

    Args:
        bridge: PDFToolBridge instance

    Returns:
        Async callable for tool execution
    """
    async def executor(tool_name: str, params: Dict[str, Any]) -> Any:
        # Only handle PDF tools
        if not tool_name.startswith("pdf_"):
            raise NotImplementedError(f"Not a PDF tool: {tool_name}")
        return await bridge.execute_tool(tool_name, params)

    return executor


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_pdf_tools():
        """Test PDF tool bridge."""
        print("Testing PDF Tool Bridge...")
        print("=" * 50)

        # Test 1: Tool definitions
        print("Test 1: Tool definitions...", end=" ")
        assert len(PDF_TOOLS) == 8, f"Expected 8 tools, got {len(PDF_TOOLS)}"
        print(f"PASS ({len(PDF_TOOLS)} tools)")

        # Test 2: Tool names
        print("Test 2: Tool names...", end=" ")
        tool_names = [t["function"]["name"] for t in PDF_TOOLS]
        expected = [
            "pdf_analyze", "pdf_extract_text", "pdf_extract_toc",
            "pdf_ocr", "pdf_to_markdown", "pdf_to_html",
            "pdf_visualize", "pdf_service_status"
        ]
        assert tool_names == expected
        print("PASS")

        # Test 3: Tool schemas
        print("Test 3: Tool schemas...", end=" ")
        for tool in PDF_TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
        print("PASS")

        # Test 4: Create bridge
        print("Test 4: Create tool bridge...", end=" ")
        bridge = PDFToolBridge()
        print("PASS")

        # Test 5: Check service status
        print("Test 5: Check service status...", end=" ")
        result = await bridge.execute_tool("pdf_service_status", {})
        if result.get("available"):
            print("PASS (service running)")
        else:
            print("SKIP (service not running)")

        # Test 6: Get stats
        print("Test 6: Get stats...", end=" ")
        stats = bridge.get_stats()
        assert "total_tools" in stats
        assert stats["total_tools"] == 8
        print("PASS")

        # Test 7: Tool executor factory
        print("Test 7: Tool executor factory...", end=" ")
        executor = get_pdf_tool_executor(bridge)
        assert callable(executor)
        print("PASS")

        # Cleanup
        await bridge.close()

        print("\n" + "=" * 50)
        print("All tests passed!")
        return True

    success = asyncio.run(test_pdf_tools())
    sys.exit(0 if success else 1)
