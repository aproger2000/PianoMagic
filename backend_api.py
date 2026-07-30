"""
PianoMagic API — Piano Edition (2 руки, квантизация)
"""

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from itertools import groupby

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from music21 import (
    converter, stream, note, chord, meter, key, instrument,
    clef, layout, metadata
)

app = FastAPI(title="PianoMagic API Piano", version="9.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

TEMP_DIR = Path("temp")
OUTPUT_DIR = Path("output")
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist
