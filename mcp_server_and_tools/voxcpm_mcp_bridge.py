"""
VoxCPM MCP Bridge
==================

Thin MCP server that exposes VoxCPM text-to-speech and voice cloning
as MCP tools for VERA. Runs via stdio transport.

Requires: pip install voxcpm (or install from local VoxCPM dir)
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

logger = logging.getLogger("voxcpm_mcp")

# Lazy-loaded model
_model = None
_model_id = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM1.5")
_output_dir = Path(os.getenv("VOXCPM_OUTPUT_DIR", "vera_memory/audio"))


def _get_model():
    """Lazy-load VoxCPM model on first use."""
    global _model
    if _model is None:
        from voxcpm import VoxCPM
        logger.info(f"Loading VoxCPM model: {_model_id}")
        _model = VoxCPM.from_pretrained(_model_id)
        logger.info("VoxCPM model loaded")
    return _model


def _ensure_output_dir():
    _output_dir.mkdir(parents=True, exist_ok=True)
    return _output_dir


try:
    from mcp.server import Server, InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, ServerCapabilities

    server = Server("voxcpm")
    _init_options = InitializationOptions(
        server_name="voxcpm",
        server_version="1.0.0",
        capabilities=ServerCapabilities(tools={}),
    )

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="text_to_speech",
                description="Generate speech audio from text using VoxCPM. Returns path to WAV file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to synthesize into speech",
                        },
                        "cfg_value": {
                            "type": "number",
                            "description": "CFG guidance value (default 2.0)",
                            "default": 2.0,
                        },
                        "inference_steps": {
                            "type": "integer",
                            "description": "Diffusion inference steps (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="voice_clone_speech",
                description="Generate speech with a cloned voice. Provide reference audio and its transcript.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to synthesize",
                        },
                        "reference_audio_path": {
                            "type": "string",
                            "description": "Path to reference audio WAV file for voice cloning",
                        },
                        "reference_transcript": {
                            "type": "string",
                            "description": "Transcript of the reference audio",
                        },
                        "cfg_value": {
                            "type": "number",
                            "description": "CFG guidance value (default 2.0)",
                            "default": 2.0,
                        },
                    },
                    "required": ["text", "reference_audio_path", "reference_transcript"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        import soundfile as sf

        model = _get_model()
        out_dir = _ensure_output_dir()
        timestamp = int(time.time())

        if name == "text_to_speech":
            text = arguments["text"]
            cfg = arguments.get("cfg_value", 2.0)
            steps = arguments.get("inference_steps", 10)

            wav = model.generate(
                text=text,
                cfg_value=cfg,
                inference_timesteps=steps,
            )
            out_path = out_dir / f"tts_{timestamp}.wav"
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return [TextContent(type="text", text=json.dumps({
                "audio_path": str(out_path),
                "sample_rate": model.tts_model.sample_rate,
                "text": text,
            }))]

        elif name == "voice_clone_speech":
            text = arguments["text"]
            ref_audio = arguments["reference_audio_path"]
            ref_text = arguments["reference_transcript"]
            cfg = arguments.get("cfg_value", 2.0)

            wav = model.generate(
                text=text,
                prompt_wav_path=ref_audio,
                prompt_text=ref_text,
                cfg_value=cfg,
            )
            out_path = out_dir / f"clone_{timestamp}.wav"
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return [TextContent(type="text", text=json.dumps({
                "audio_path": str(out_path),
                "sample_rate": model.tts_model.sample_rate,
                "text": text,
                "reference_audio": ref_audio,
            }))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, _init_options)

    if __name__ == "__main__":
        import asyncio
        asyncio.run(main())

except ImportError:
    # Fallback: if mcp SDK not available, try fastmcp
    try:
        from fastmcp import FastMCP

        mcp = FastMCP("voxcpm")

        @mcp.tool()
        def text_to_speech(text: str, cfg_value: float = 2.0, inference_steps: int = 10) -> str:
            """Generate speech audio from text. Returns path to WAV file."""
            import soundfile as sf

            model = _get_model()
            out_dir = _ensure_output_dir()

            wav = model.generate(text=text, cfg_value=cfg_value, inference_timesteps=inference_steps)
            out_path = out_dir / f"tts_{int(time.time())}.wav"
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return json.dumps({"audio_path": str(out_path), "text": text})

        @mcp.tool()
        def voice_clone_speech(text: str, reference_audio_path: str, reference_transcript: str, cfg_value: float = 2.0) -> str:
            """Generate speech with a cloned voice from reference audio."""
            import soundfile as sf

            model = _get_model()
            out_dir = _ensure_output_dir()

            wav = model.generate(
                text=text,
                prompt_wav_path=reference_audio_path,
                prompt_text=reference_transcript,
                cfg_value=cfg_value,
            )
            out_path = out_dir / f"clone_{int(time.time())}.wav"
            sf.write(str(out_path), wav, model.tts_model.sample_rate)
            return json.dumps({"audio_path": str(out_path), "text": text})

        if __name__ == "__main__":
            mcp.run(transport="stdio")

    except ImportError:
        print("Error: Neither 'mcp' nor 'fastmcp' package found. Install one.", file=sys.stderr)
        sys.exit(1)
