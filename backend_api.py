"""
PianoMagic API Pro v3 — MuseScore headless + fallback
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

app = FastAPI(title="PianoMagic API Pro v3", version="8.0.0")

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

_basic_pitch_loaded = False

def get_predict():
    global _basic_pitch_loaded
    if not _basic_pitch_loaded:
        print("[INIT] Loading Basic Pitch model...")
        from basic_pitch.inference import predict as _predict
        _basic_pitch_loaded = True
        print("[INIT] Model loaded")
        return _predict
    else:
        from basic_pitch.inference import predict as _predict
        return _predict


def transcribe_sync(input_path: Path, midi_path: Path):
    print(f"[TRANSCRIBE] {input_path}")
    predict_func = get_predict()
    _, midi_data, _ = predict_func(str(input_path))
    midi_data.write(str(midi_path))
    print(f"[TRANSCRIBE] MIDI: {midi_path}")


def generate_pdf_sync(midi_path: Path, pdf_path: Path):
    """Генерация PDF с fallback."""
    print(f"[PDF] {midi_path} -> {pdf_path}")
    
    mscore = (
        shutil.which("mscore") or shutil.which("mscore4") or
        shutil.which("musescore") or shutil.which("musescore3")
    )
    
    if mscore:
        try:
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["QT_QPA_PLATFORMTHEME"] = ""
            
            subprocess.run(
                [mscore, str(midi_path), "-o", str(pdf_path)],
                check=True, capture_output=True, timeout=60, env=env
            )
            print(f"[PDF] MuseScore OK: {pdf_path}")
            return
        except Exception as e:
            print(f"[PDF] MuseScore failed: {e}, trying fallback...")
    
    try:
        s = converter.parse(str(midi_path))
        for part in s.parts:
            part.insert(0, instrument.Piano())
        s = s.quantize()
        s.write("lily.pdf", fp=str(pdf_path))
        print(f"[PDF] music21/LilyPond OK: {pdf_path}")
        return
    except Exception as e:
        print(f"[PDF] music21 failed: {e}")
    
    raise RuntimeError("Не удалось сгенерировать PDF. Установите MuseScore или LilyPond.")


async def process_audio_async(job_id: str, input_path: Path):
    try:
        jobs[job_id]["status"] = "transcribing"
        jobs[job_id]["message"] = "AI анализирует аудио..."
        
        job_dir = TEMP_DIR / job_id
        job_dir.mkdir(exist_ok=True)
        
        midi_path = job_dir / "transcription.mid"
        pdf_path = OUTPUT_DIR / f"{job_id}.pdf"
        
        await asyncio.to_thread(transcribe_sync, input_path, midi_path)
        
        jobs[job_id]["status"] = "generating_pdf"
        jobs[job_id]["message"] = "Генерация нотного листа..."
        
        await asyncio.to_thread(generate_pdf_sync, midi_path, pdf_path)
        
        try:
            shutil.rmtree(job_dir)
            os.remove(input_path)
        except:
            pass
        
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["pdf_url"] = f"/download/{job_id}.pdf"
        jobs[job_id]["message"] = "Готово!"
        print(f"[DONE] Job {job_id}")
        
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
        raise HTTPException(status_code=413, detail="Файл слишком большой")
    
    allowed = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат")
    
    job_id = str(uuid.uuid4())[:8]
    input_path = TEMP_DIR / job_id / file.filename
    input_path.parent.mkdir(exist_ok=True)
    
    with open(input_path, "wb") as f:
        f.write(content)
    
    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "message": "Начинаем обработку...",
        "filename": file.filename
    }
    
    asyncio.create_task(process_audio_async(job_id, input_path))
    
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
    return {"status": "ok", "service": "PianoMagic API Pro v3"}


@app.get("/")
async def root():
    return {"service": "PianoMagic API Pro v3", "version": "8.0.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
