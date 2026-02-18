#!/usr/bin/env python3
"""
PDF Processing Module for VERA
===============================

Provides PDF document analysis and extraction capabilities:
- Layout analysis and segmentation
- OCR for scanned documents
- Text extraction by content type
- Table of contents extraction
- Conversion to Markdown/HTML
- Translation support

Uses the pdf-document-layout-analysis microservice via HTTP API.

Usage:
    from pdf_processing import PDFClient, PDF_TOOLS, PDFToolBridge

    # Direct client usage
    client = PDFClient()
    result = await client.analyze_pdf("document.pdf")

    # Tool bridge for LLM integration
    bridge = PDFToolBridge()
    result = await bridge.execute_tool("pdf_analyze", {"file_path": "doc.pdf"})
"""

from .client import PDFClient, PDFServiceConfig
from .tools import (
    PDF_TOOLS,
    PDFToolBridge,
    create_pdf_bridge,
    get_pdf_tool_executor
)

__all__ = [
    # Client
    'PDFClient',
    'PDFServiceConfig',
    # Tools
    'PDF_TOOLS',
    'PDFToolBridge',
    'create_pdf_bridge',
    'get_pdf_tool_executor',
]
