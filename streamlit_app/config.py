from datetime import datetime
from typing import Tuple
import os
import boto3
from botocore.exceptions import ClientError

# API Configuration
API_URL = "https://k6gnqai4bffo6n4ras6ixyckmq0cbbwy.lambda-url.eu-central-1.on.aws/"

# S3 Settings
S3_BUCKET = "gelir-vergisi "  # for outputs
S3_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
S3_RECORDING_BUCKET = "gelir-vergisi"
S3_AUDIO_PREFIX = "recordings/"
S3_IMAGE_PREFIX = "images/"

# Get AWS credentials from environment variables (Streamlit Cloud secrets)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Create AWS session with credentials if available
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    aws_session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )
else:
    # Fallback to default credential chain (for local development)
    aws_session = boto3.Session(region_name=S3_REGION)

# AWS Clients
s3 = aws_session.client("s3")
polly = aws_session.client("polly")

MAX_POLLY_CHARS = 2500

def get_aws_account_info() -> dict:
    """Get AWS account information to verify credentials."""
    try:
        sts = aws_session.client("sts")
        identity = sts.get_caller_identity()
        return {
            "account_id": identity.get("Account"),
            "user_arn": identity.get("Arn"),
            "user_id": identity.get("UserId")
        }
    except Exception as e:
        return {"error": str(e)}

def check_s3_access(bucket_name: str) -> Tuple[bool, str]:
    """Check if we have write access to the S3 bucket."""
    try:
        # Try to head the bucket to verify access
        s3.head_bucket(Bucket=bucket_name)
        return True, ""
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        error_msg = e.response.get("Error", {}).get("Message", "")
        full_error = str(e)
        
        if error_code == "403":
            # Get account info for debugging
            account_info = get_aws_account_info()
            debug_info = f"\n\n**Debug Info:**\n- AWS Account: {account_info.get('account_id', 'Unknown')}\n- User ARN: {account_info.get('user_arn', 'Unknown')}"
            return False, f"Access Denied (403): {error_msg}{debug_info}\n\nPossible causes:\n1. Bucket policy blocking access\n2. Bucket encryption requirements\n3. Wrong AWS account\n4. Bucket ACL restrictions"
        elif error_code == "404":
            return False, f"Bucket '{bucket_name}' not found in region '{S3_REGION}'. Please verify:\n1. Bucket name is correct\n2. Bucket exists in region '{S3_REGION}'"
        else:
            return False, f"AWS Error ({error_code}): {error_msg}\nFull error: {full_error}"
    except Exception as e:
        return False, f"Error checking S3 access: {str(e)}"

def tts_polly(text: str):
    """Convert text to speech using AWS Polly and return audio bytes."""
    response = polly.synthesize_speech(
        Engine="neural",
        VoiceId="Burcu",
        OutputFormat="mp3",
        Text=text
    )
    return response["AudioStream"].read()

def split_text_for_polly(text: str, limit: int = MAX_POLLY_CHARS):
    """
    Splits long text into chunks smaller than Polly's limit.
    Splits by sentences first; if needed, falls back to word splitting.
    """
    chunks = []
    current = ""

    sentences = text.split(". ")
    for sentence in sentences:
        # add back separator
        sentence = sentence.strip()
        if not sentence.endswith("."):
            sentence += "."
        sentence += " "

        # Fits current chunk?
        if len(current) + len(sentence) <= limit:
            current += sentence
        else:
            # If sentence alone exceeds limit, split by words
            if len(sentence) > limit:
                words = sentence.split(" ")
                temp = ""
                for w in words:
                    if len(temp) + len(w) + 1 <= limit:
                        temp += w + " "
                    else:
                        chunks.append(temp.strip())
                        temp = w + " "
                if temp.strip():
                    chunks.append(temp.strip())
                continue

            chunks.append(current.strip())
            current = sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks

def tts_polly_safe(text: str):
    """
    Uses your original tts_polly() and safely handles long text
    by splitting → synthesizing each part → concatenating MP3 bytes.
    """
    parts = split_text_for_polly(text)

    full_audio = b""
    for i, chunk in enumerate(parts):
        print(f"Generating chunk {i+1}/{len(parts)} ({len(chunk)} chars)")
        full_audio += tts_polly(chunk)

    return full_audio
