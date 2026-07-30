"""
PianoMagic API — Pro версия (полноценный AI на сервере)
FastAPI + Basic Pitch (TensorFlow) + music21 + MuseScore
"""

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from music21 import converter, instrument
from basic_pitch.inference import predict

app = FastAPI(title="PianoMagic API Pro", version="6.0.0")

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
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024
jobs = {}


def transcribe_sync(input_path: Path, midi_path: Path):
    """Синхронная транскрипция в отдельном потоке."""
    print(f"[TRANSCRIBE] Starting Basic Pitch for: {input_path}")
    _, midi_data, _ = predict(str(input_path))
    midi_data.write(str(midi_path))
    print(f"[TRANSCRIBE] MIDI saved: {midi_path}")


def generate_pdf_sync(midi_path: Path, pdf_path: Path):
    """Синхронная генерация PDF."""
    print(f"[PDF] Starting: {midi_path} -> {pdf_path}")
    mscore = (
        shutil.which("mscore") or shutil.which("mscore4") or
        shutil.which("musescore") or shutil.which("musescore3")
    )
    if mscore:
        subprocess.run(
            [mscore, str(midi_path), "-o", str(pdf_path)],
            check=True, capture_output=True, timeout=60
        )
    else:
        s = converter.parse(str(midi_path))
        for part in s.parts:
            part.insert(0, instrument.Piano())
        s = s.quantize()
        s.write("lily.pdf", fp=str(pdf_path))
    print(f"[PDF] Done: {pdf_path}")


async def process_audio_async(job_id: str, input_path: Path):
    """Асинхронная обработка."""
    try:
        jobs[job_id]["status"] = "transcribing"
        jobs[job_id]["message"] = "AI анализирует аудио..."

        job_dir = TEMP_DIR / job_id
        job_dir.mkdir(exist_ok=True)

        midi_path = job_dir / "transcription.mid"
        pdf_path = OUTPUT_DIR / f"{job_id}.pdf"

        # Шаг 1: Audio -> MIDI (в отдельном потоке)
        await asyncio.to_thread(transcribe_sync, input_path, midi_path)

        jobs[job_id]["status"] = "generating_pdf"
        jobs[job_id]["message"] = "Генерация нотного листа..."

        # Шаг 2: MIDI -> PDF (в отдельном потоке)
        await asyncio.to_thread(generate_pdf_sync, midi_path, pdf_path)

        # Очистка
        try:
            shutil.rmtree(job_dir)
            os.remove(input_path)
        except:
            pass

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["pdf_url"] = f"/download/{job_id}.pdf"
        jobs[job_id]["message"] = "Готово!"
        print(f"[DONE] Job {job_id} completed")

    except Exception as e:
        print(f"[ERROR] Job {job_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)


@app.post("/transcribe/file")
async def transcribe_file(file: UploadFile = File(...)):
    print(f"[UPLOAD] {file.filename}, size: {file.size}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой. Максимум 50 МБ.")

    allowed = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат")

    job_id = str(uuid.uuid4())[:8]
    input_path = TEMP_DIR / job_id / file.filename
    input_path.parent.mkdir(exist_ok=True)

    with open(input_path, "wb") as f:
        f.write(content)
    print(f"[UPLOAD] Saved: {input_path}")

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "message": "Начинаем обработку...",
        "filename": file.filename
    }

    asyncio.create_task(process_audio_async(job_id, input_path))
    print(f"[UPLOAD] Task started: {job_id}")

    return JSONResponse(content={
        "job_id": job_id,
        "status": "processing",
        "message": "Обработка начата"
    })


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return JSONResponse(content=jobs[job_id])


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path=file_path, filename=filename, media_type="application/pdf")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "PianoMagic API Pro"}


@app.get("/")
async def root():
    return {"service": "PianoMagic API Pro", "version": "6.0.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
