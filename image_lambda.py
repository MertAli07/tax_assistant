import boto3
import base64
import json
import mimetypes
import urllib.parse
import urllib.request
import time
import uuid
from typing import Tuple, Optional, List, Dict, Any

# --- Clients (reuse) ---
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
transcribe = boto3.client("transcribe")

# --- Config ---
MODEL_ID = "arn:aws:bedrock:us-east-1:777179738691:inference-profile/global.anthropic.claude-sonnet-4-5-20250929-v1:0"
MAX_TOKENS = 2048
TRANSCRIBE_WAIT_SEC = 75
TRANSCRIBE_POLL_SEC = 3

ANALYSIS_PROMPT = (
    "Görseli analiz et. Metin varsa metnin ana fikrini özetle. "
    "Hem görsel hem metin varsa önce metni özetle, sonra görsel kompozisyonunu kısaca açıkla. "
    "Uydurma yapma."
    "Maksimum 7 cümlede özetle."
)

# ----------------- helpers (common) -----------------
def _infer_media_type(key: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    key_no_q = key.split("?", 1)[0]
    mt, _ = mimetypes.guess_type(key_no_q)
    return mt if mt in {"image/jpeg", "image/png"} else "image/jpeg"

def _parse_s3_from_uri(s3_uri: str) -> Tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid s3Uri: {s3_uri}")
    without = s3_uri[len("s3://") :]
    bucket, _, key = without.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid s3Uri (missing bucket/key): {s3_uri}")
    return bucket, key

def _extract_from_s3_event(event) -> List[str]:
    uris = []
    try:
        for rec in event.get("Records", []):
            b = rec["s3"]["bucket"]["name"]
            k = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
            uris.append(f"s3://{b}/{k}")
    except Exception:
        pass
    return uris

# NEW: Flow/Inline Lambda input'tan "data" nesnesini çıkar
def _pluck_flow_data(event: dict) -> Optional[dict]:
    # 1) Top-level "data"
    if isinstance(event.get("data"), dict):
        return event["data"]
    # 2) node.inputs[*].name == "data"
    try:
        for inp in event.get("node", {}).get("inputs", []):
            if inp.get("name") == "data":
                val = inp.get("value")
                if isinstance(val, str):
                    try:
                        return json.loads(val)
                    except Exception:
                        return None
                if isinstance(val, dict):
                    return val
    except Exception:
        pass
    return None

def _extract_from_flow_node(event) -> Dict[str, Any]:
    """
    Flow / Bedrock Flow:
      - Tercihen 'data' nesnesini oku ve içinden alanları çek.
      - Yoksa node.inputs'taki tekil alan adlarını dene (eski desen).
    """
    # Öncelik: data nesnesi
    doc = _pluck_flow_data(event)
    if isinstance(doc, dict):
        img = doc.get("image_path")
        aud = doc.get("audio_path")
        user_input = doc.get("user_input") or doc.get("message") or doc.get("prompt")
        media_type = doc.get("mediaType")
        if isinstance(img, str): img = [img]
        if isinstance(aud, str): aud = [aud]
        return {
            "image_path": img, "audio_path": aud,
            "user_input": user_input, "mediaType": media_type
        }

    # Geriye uyumluluk: node.inputs tekil alanlar
    out = {"image_path": None, "audio_path": None, "user_input": None, "mediaType": None}
    try:
        inputs = event.get("node", {}).get("inputs", [])
        vals = {i.get("name"): i.get("value") for i in inputs if isinstance(i, dict)}
        img = vals.get("image_path")
        aud = vals.get("audio_path")
        if isinstance(img, str): img = [img]
        if isinstance(aud, str): aud = [aud]
        out["image_path"] = img
        out["audio_path"] = aud
        out["user_input"] = vals.get("user_input") or vals.get("message") or vals.get("prompt")
        out["mediaType"] = vals.get("mediaType")
    except Exception:
        pass
    return out

def _extract_inputs(event) -> Tuple[List[str], List[str], str, Optional[str]]:
    """
    DÖNÜŞ: (image_uris[], audio_uris[], user_input, media_type_hint)
    Öncelik: Flow 'data' nesnesi -> event alanları -> S3 event -> node tekil girdiler
    """
    # 0) Flow 'data' nesnesi
    doc = _pluck_flow_data(event) or {}
    imgs: List[str] = []
    auds: List[str] = []
    user_input = doc.get("user_input") or ""
    media_hint = doc.get("mediaType")

    # 1) doc içindeki listeler
    image_path = doc.get("image_path")
    audio_path = doc.get("audio_path")
    if isinstance(image_path, list): imgs = image_path
    elif isinstance(image_path, str): imgs = [image_path]
    if isinstance(audio_path, list): auds = audio_path
    elif isinstance(audio_path, str): auds = [audio_path]

    # 2) top-level fallback (Lambda konsol testi vs.)
    if not user_input:
        user_input = event.get("user_input") or event.get("message") or event.get("prompt") or ""
    media_hint = media_hint or event.get("mediaType")
    if not imgs:
        ip = event.get("image_path")
        if isinstance(ip, list): imgs = ip
        elif isinstance(ip, str): imgs = [ip]
    if not auds:
        ap = event.get("audio_path")
        if isinstance(ap, list): auds = ap
        elif isinstance(ap, str): auds = [ap]

    # 3) single uri'lar
    s3_uri = event.get("s3Uri") or event.get("s3_uri")
    audio_uri = event.get("audioUri") or event.get("audio_uri")
    if s3_uri and not imgs: imgs = [s3_uri]
    if audio_uri and not auds: auds = [audio_uri]

    # 4) S3 event
    if not imgs:
        rec_uris = _extract_from_s3_event(event)
        if rec_uris:
            imgs = rec_uris

    # 5) node tekil girdiler (tam yedek)
    if not imgs or not auds or not user_input or not media_hint:
        node_vals = _extract_from_flow_node(event)
        if not imgs and node_vals.get("image_path"): imgs = node_vals["image_path"]
        if not auds and node_vals.get("audio_path"): auds = node_vals["audio_path"]
        if not user_input and node_vals.get("user_input"): user_input = node_vals["user_input"]
        if not media_hint and node_vals.get("mediaType"): media_hint = node_vals["mediaType"]

    return imgs, auds, user_input, media_hint

# ----------------- image pipeline -----------------
def _read_image_as_b64(s3_uri: str) -> Dict[str, Any]:
    bkt, key = _parse_s3_from_uri(s3_uri)
    obj = s3.get_object(Bucket=bkt, Key=key)
    img_b64 = base64.b64encode(obj["Body"].read()).decode("utf-8")
    return {"bucket": bkt, "key": key, "b64": img_b64, "mime": _infer_media_type(key)}

def _invoke_claude(image_b64: str, mime: str) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type":"base64","media_type": mime,"data": image_b64}},
                    {"type": "text", "text": ANALYSIS_PROMPT}
                ]
            }
        ]
    }
    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        accept="application/json",
        contentType="application/json",
    )
    out = json.loads(resp["body"].read())
    return "".join([b.get("text","") for b in out.get("content",[]) if b.get("type")=="text"]).strip()

def process_images(image_uris: List[str], media_type_hint: Optional[str]) -> Dict[str, Any]:
    if not image_uris:
        return {"status": "no_image", "results": {}, "errors": None, "count": 0, "requested": 0}
    results_map: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    for idx, uri in enumerate(image_uris, start=1):
        key_name = f"image_{idx}"
        try:
            meta = _read_image_as_b64(uri)
            mime = media_type_hint or meta["mime"]
            text = _invoke_claude(meta["b64"], mime)
            results_map[key_name] = text or "(empty response)"
        except Exception as e:
            errors[key_name] = f"{uri} -> {e}"
    return {"status": "ok" if results_map else "error", "results": results_map, "errors": errors or None,
            "count": len(results_map), "requested": len(image_uris)}

# ----------------- audio pipeline (Transcribe) -----------------
def _infer_audio_format(key: str) -> Optional[str]:
    key = key.lower()
    for ext, fmt in [(".mp3","mp3"), (".wav","wav"), (".mp4","mp4"), (".m4a","m4a"),
                     (".flac","flac"), (".ogg","ogg"), (".webm","webm")]:
        if key.endswith(ext): return fmt
    return None

def _start_and_wait_transcribe(s3_uri: str) -> str:
    job_name = f"flow-asr-{uuid.uuid4().hex[:12]}"
    media_fmt = _infer_audio_format(s3_uri)
    params = {"TranscriptionJobName": job_name, "Media": {"MediaFileUri": s3_uri}, "IdentifyLanguage": True}
    if media_fmt: params["MediaFormat"] = media_fmt
    transcribe.start_transcription_job(**params)
    deadline = time.time() + TRANSCRIBE_WAIT_SEC
    while time.time() < deadline:
        job = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        status = job["TranscriptionJob"]["TranscriptionJobStatus"]
        if status == "COMPLETED":
            uri = job["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
            with urllib.request.urlopen(uri) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            try:
                return data["results"]["transcripts"][0]["transcript"]
            except Exception:
                return json.dumps(data, ensure_ascii=False)
        if status == "FAILED":
            reason = job["TranscriptionJob"].get("FailureReason", "Unknown")
            raise RuntimeError(f"Transcribe failed: {reason}")
        time.sleep(TRANSCRIBE_POLL_SEC)
    raise TimeoutError("Transcribe timed out; increase TRANSCRIBE_WAIT_SEC or Lambda timeout.")

def process_audios(audio_uris: List[str]) -> Dict[str, Any]:
    if not audio_uris:
        return {"status": "no_audio", "results": {}, "errors": None, "count": 0, "requested": 0}
    results_map: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    for idx, uri in enumerate(audio_uris, start=1):
        key_name = f"audio_{idx}"
        try:
            transcript = _start_and_wait_transcribe(uri)
            results_map[key_name] = transcript or "(empty transcript)"
        except Exception as e:
            errors[key_name] = f"{uri} -> {e}"
    return {"status": "ok" if results_map else "error", "results": results_map, "errors": errors or None,
            "count": len(results_map), "requested": len(audio_uris)}

# ----------------- handler -----------------
def lambda_handler(event, context):
    print(f"event: {event}")
    images, audios, user_input, media_hint = _extract_inputs(event)
    image_out = process_images(images, media_hint)
    audio_out = process_audios(audios)
    return {"images": image_out, "audios": audio_out, "user_input": user_input}