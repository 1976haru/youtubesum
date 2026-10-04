"""Headless JSON bridge for ShopSource; never opens the Tkinter application."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None


PROTOCOL = "1.0"
ASSET_TYPES = {"HERO_BANNER", "COLLECTION_SQUARE", "COLLECTION_CARD"}


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class ImageProvider(ABC):
    name = "BASE"
    model = ""
    generative = False

    @abstractmethod
    def generate(self, job: dict) -> list[dict]:
        """Return output candidate descriptions; implementations must stay in output_dir."""


class LegacyCropProvider(ImageProvider):
    """Non-generative crop/resize adapter for a user-supplied reference image."""
    name = "LEGACY_CROP"
    model = "Pillow-ImageOps"

    def generate(self, job: dict) -> list[dict]:
        if Image is None:
            raise RuntimeError("DEPENDENCY_MISSING:Pillow")
        refs = job.get("reference_images") or []
        if not refs:
            return []
        output = Path(job["output_dir"]).resolve()
        w, h = int(job["target"]["width"]), int(job["target"]["height"])
        count = max(1, min(8, int(job.get("output_count", 1))))
        candidates = []
        for i, raw in enumerate(refs[:count], start=1):
            source = Path(raw).expanduser().resolve(strict=True)
            if not source.is_file():
                continue
            target = output / f"candidate-{i:02d}.jpg"
            with Image.open(source) as image:
                image = ImageOps.fit(image.convert("RGB"), (w, h), method=Image.Resampling.LANCZOS)
                image.save(target, format="JPEG", quality=92, optimize=True)
            candidates.append({"path": str(target), "technical_score": 0.0,
                               "warnings": ["NON_GENERATIVE_CROP_FROM_USER_REFERENCE"]})
        return candidates


def _error(code: str, message_ko: str) -> dict:
    return {"code": code, "message_ko": message_ko}


def capabilities() -> dict:
    return {"bridge": "shopsource-image-studio", "schema_versions": [PROTOCOL], "asset_types": sorted(ASSET_TYPES),
            "providers": ["LEGACY_CROP", "LOCAL_GENERATOR"], "supports_reference_images": True,
            "supports_output_count": True, "supports_no_text_policy": True, "supports_unicode_paths": True,
            "generator": {"status": "WAITING_FOR_CONFIGURATION", "ready": False,
                          "message_ko": "현재 설치본에는 실제 로컬 생성 모델이 연결되지 않았습니다. prompt 복사 또는 승인된 참고 이미지 crop을 사용할 수 있습니다."}}


def doctor() -> dict:
    checks = {"python": {"ok": sys.version_info >= (3, 10), "version": sys.version.split()[0]},
              "pillow": {"ok": Image is not None}, "numpy": {"ok": False}, "opencv": {"ok": False},
              "generator": {"ok": False, "message_ko": capabilities()["generator"]["message_ko"]}}
    try:
        import numpy
        checks["numpy"] = {"ok": True, "version": numpy.__version__}
    except ImportError:
        pass
    try:
        import cv2
        checks["opencv"] = {"ok": True, "version": cv2.__version__}
    except ImportError:
        pass
    writable = False
    try:
        with tempfile.TemporaryDirectory(prefix="shopsource-bridge-doctor-"):
            writable = True
    except OSError:
        pass
    checks["temp_output"] = {"ok": writable}
    return {"python": sys.executable, "checks": checks,
            "core_ready": checks["python"]["ok"] and checks["pillow"]["ok"] and writable,
            "generator_ready": False}


def _validate_job(job: dict) -> tuple[Path, list[str]]:
    required = ("job_id", "store_id", "asset_type", "prompt", "target", "output_dir")
    missing = [x for x in required if x not in job]
    if missing:
        raise ValueError("Missing required job fields: " + ", ".join(missing))
    if job.get("schema_version") != PROTOCOL:
        raise ValueError("Unsupported schema_version")
    if job["asset_type"] not in ASSET_TYPES:
        raise ValueError("Unsupported asset_type")
    output = Path(job["output_dir"]).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    refs = []
    for raw in job.get("reference_images") or []:
        source = Path(raw).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("Reference image is not a file")
        refs.append(str(source))
    job["reference_images"] = refs
    job["output_dir"] = str(output)
    job["output_count"] = max(1, min(8, int(job.get("output_count", 1))))
    return output, refs


def execute_job(job: dict, *, provider: ImageProvider | None = None) -> dict:
    result = {"schema_version": PROTOCOL, "job_id": str(job.get("job_id", "")), "status": "FAILED",
              "provider": None, "model": None, "created_at": datetime.now(timezone.utc).isoformat(),
              "recommended_candidate_id": None, "candidates": [], "warnings": [], "error": None}
    try:
        output, _ = _validate_job(job)
        if Image is None:
            result["error"] = _error("DEPENDENCY_MISSING", "이미지 검사를 위해 YouTubeSum 환경에 Pillow 설치가 필요합니다.")
            return result
        selected = provider or LegacyCropProvider()
        if selected.name == "LEGACY_CROP" and not job.get("reference_images"):
            result.update(status="WAITING_FOR_CONFIGURATION", provider=selected.name, model=selected.model)
            result["error"] = _error("GENERATOR_NOT_CONFIGURED", "실제 이미지 생성 모델이 아직 연결되지 않았습니다. ShopSource의 prompt 복사와 파일 업로드를 이용하세요.")
            return result
        raw_candidates = selected.generate(job)
        seen = set()
        for i, item in enumerate(raw_candidates, start=1):
            try:
                path = Path(item["path"]).expanduser().resolve(strict=True)
                path.relative_to(output)
                if not path.is_file() or path.stat().st_size <= 0 or path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    width, height, fmt = image.width, image.height, image.format
                target_w, target_h = int(job["target"]["width"]), int(job["target"]["height"])
                if width < min(512, target_w) or height < min(512, target_h):
                    continue
                if abs((width / height) / (target_w / target_h) - 1) > 0.2:
                    continue
                digest = _digest(path)
                if digest in seen:
                    result["warnings"].append("DUPLICATE_CANDIDATE_HASH_REJECTED")
                    continue
                seen.add(digest)
                candidate_id = str(item.get("candidate_id") or f"candidate-{i:02d}")
                result["candidates"].append({"candidate_id": candidate_id, "path": str(path),
                    "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "width": width, "height": height, "sha256": digest,
                    "prompt_hash": hashlib.sha256(str(job["prompt"]).encode("utf-8")).hexdigest(),
                    "source_type": "GENERATED" if selected.generative else "NON_GENERATIVE_DERIVATIVE",
                    "technical_score": float(item.get("technical_score", 0)), "warnings": list(item.get("warnings", []))})
            except (KeyError, OSError, ValueError, TypeError):
                result["warnings"].append("INVALID_CANDIDATE_REJECTED")
        result.update(provider=selected.name, model=selected.model)
        if not result["candidates"]:
            result["status"] = "FAILED"
            result["error"] = _error("NO_VALID_CANDIDATES", "검사를 통과한 후보가 없습니다. 참고 이미지 또는 생성기 설정을 확인하세요.")
        else:
            result["status"] = "SUCCEEDED" if len(result["candidates"]) == len(raw_candidates) else "PARTIAL"
            result["recommended_candidate_id"] = max(result["candidates"], key=lambda x: x["technical_score"])["candidate_id"]
        return result
    except FileNotFoundError:
        result["status"] = "FAILED"; result["error"] = _error("INPUT_MISSING", "요청 이미지 파일을 찾을 수 없습니다.")
    except (OSError, TypeError, ValueError, KeyError) as exc:
        result["status"] = "FAILED"; result["error"] = _error("INVALID_JOB", str(exc)[:300])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Headless ShopSource image bridge")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--health", action="store_true")
    mode.add_argument("--capabilities", action="store_true")
    mode.add_argument("--doctor", action="store_true")
    parser.add_argument("--job")
    parser.add_argument("--result")
    args = parser.parse_args(argv)
    if args.health:
        print(json.dumps({"available": True, "status": "BRIDGE_READY", "bridge": "shopsource-image-studio", "message_ko": "YouTubeSum headless 브리지가 준비되었습니다."}, ensure_ascii=False)); return 0
    if args.capabilities:
        print(json.dumps(capabilities(), ensure_ascii=False)); return 0
    if args.doctor:
        value = doctor(); print(json.dumps(value, ensure_ascii=False)); return 0 if value["core_ready"] else 2
    if not args.job or not args.result:
        parser.error("--job and --result are required together")
    result_path = Path(args.result).expanduser().resolve()
    try:
        job = json.loads(Path(args.job).read_text(encoding="utf-8"))
        result = execute_job(job)
    except (OSError, json.JSONDecodeError) as exc:
        result = {"schema_version": PROTOCOL, "job_id": "", "status": "FAILED", "provider": None, "model": None,
                  "created_at": datetime.now(timezone.utc).isoformat(), "recommended_candidate_id": None,
                  "candidates": [], "warnings": [], "error": _error("JOB_READ_FAILED", str(exc)[:200])}
    _atomic_json(result_path, result)
    print(json.dumps({"status": result["status"], "job_id": result["job_id"], "message_ko": (result.get("error") or {}).get("message_ko", "")}, ensure_ascii=False))
    return 1 if result["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
