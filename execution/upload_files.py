"""
File Upload to Cloudflare R2 (S3-compatible)
Uploads files from URLs to R2 storage for modeling requests.

Usage:
    python upload_files.py --files '[{"name": "model.glb", "url": "https://..."}]' --prefix "requests/123"
"""

import os
import sys
import json
import argparse
import requests
import uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environment variables
load_dotenv()

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")

# 3D file extensions to prioritize
FILE_3D_EXTENSIONS = {'.glb', '.usdz', '.obj', '.fbx', '.stl', '.gltf', '.dae'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}


def get_s3_client():
    """Initialize S3 client for R2"""
    if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_ENDPOINT_URL]):
        raise ValueError("R2 configuration incomplete in .env")
    
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4')
    )


def download_file(url: str, temp_path: Path) -> bool:
    """Download file from URL to temp path"""
    try:
        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()
        
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True
    except Exception as e:
        print(f"⚠️  Download failed for {url}: {str(e)[:100]}")
        return False


def get_content_type(filename: str) -> str:
    """Get content type based on file extension"""
    ext = Path(filename).suffix.lower()
    
    content_types = {
        '.glb': 'model/gltf-binary',
        '.gltf': 'model/gltf+json',
        '.usdz': 'model/vnd.usdz+zip',
        '.obj': 'text/plain',
        '.fbx': 'application/octet-stream',
        '.stl': 'application/sla',
        '.dae': 'model/vnd.collada+xml',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.pdf': 'application/pdf',
    }
    
    return content_types.get(ext, 'application/octet-stream')


def upload_to_r2(local_path: Path, remote_key: str) -> str | None:
    """Upload file to R2 and return public URL"""
    try:
        client = get_s3_client()
        
        content_type = get_content_type(local_path.name)
        
        client.upload_file(
            str(local_path),
            R2_BUCKET_NAME,
            remote_key,
            ExtraArgs={
                'ContentType': content_type,
                'ACL': 'public-read'
            }
        )
        
        # Build public URL
        # R2 public URL format: https://{bucket}.{account}.r2.dev/{key}
        # Or custom domain if configured
        public_url = f"{R2_ENDPOINT_URL.replace('r2.cloudflarestorage.com', 'r2.dev')}/{R2_BUCKET_NAME}/{remote_key}"
        
        return public_url
        
    except Exception as e:
        print(f"❌ Upload failed: {str(e)[:200]}")
        return None


def upload_files(files: list, prefix: str = None) -> dict:
    """
    Upload multiple files to R2.
    
    Args:
        files: List of {"name": "filename", "url": "source_url"} or {"name": "filename", "path": "local_path"}
        prefix: Optional prefix for R2 keys (e.g., "requests/abc123")
    
    Returns:
        {
            "uploaded": [{"name": str, "url": str}],
            "failed": [{"name": str, "error": str}],
            "success": bool
        }
    """
    if not files:
        return {"uploaded": [], "failed": [], "success": True}
    
    # Generate prefix if not provided
    if not prefix:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"requests/{timestamp}_{uuid.uuid4().hex[:8]}"
    
    # Ensure .tmp directory exists
    tmp_dir = Path(".tmp")
    tmp_dir.mkdir(exist_ok=True)
    
    uploaded = []
    failed = []
    
    for file_info in files:
        name = file_info.get("name", f"file_{uuid.uuid4().hex[:8]}")
        url = file_info.get("url")
        local_path = file_info.get("path")
        
        print(f"📤 Processing: {name}")
        
        # Download if URL provided
        if url and not local_path:
            temp_path = tmp_dir / name
            if not download_file(url, temp_path):
                failed.append({"name": name, "error": "Download failed"})
                continue
            local_path = temp_path
        elif local_path:
            local_path = Path(local_path)
            if not local_path.exists():
                failed.append({"name": name, "error": "File not found"})
                continue
        else:
            failed.append({"name": name, "error": "No URL or path provided"})
            continue
        
        # Upload to R2
        remote_key = f"{prefix}/{name}"
        public_url = upload_to_r2(local_path, remote_key)
        
        # Clean up temp file if we downloaded it
        if url and local_path.parent == tmp_dir:
            try:
                local_path.unlink()
            except Exception:
                pass
        
        if public_url:
            print(f"✅ Uploaded: {name}")
            uploaded.append({"name": name, "url": public_url})
        else:
            failed.append({"name": name, "error": "Upload failed"})
    
    success = len(failed) == 0
    
    return {
        "uploaded": uploaded,
        "failed": failed,
        "success": success,
        "prefix": prefix
    }


def main():
    parser = argparse.ArgumentParser(description="Upload files to Cloudflare R2")
    parser.add_argument("--files", required=True, help="JSON array of files")
    parser.add_argument("--prefix", help="R2 key prefix")
    parser.add_argument("--output", help="Output JSON file path")
    
    args = parser.parse_args()
    
    files = json.loads(args.files)
    
    print(f"📦 Uploading {len(files)} files to R2...")
    
    result = upload_files(files, args.prefix)
    
    print(f"\n📊 Results: {len(result['uploaded'])} uploaded, {len(result['failed'])} failed")
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"💾 Result saved to {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    return result


if __name__ == "__main__":
    main()
