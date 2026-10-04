import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import shopsource_bridge as bridge


def job(tmp_path, **updates):
    data = {"schema_version":"1.0", "job_id":"job-001", "store_id":"001", "store_name":"Cabin Tidy",
            "asset_type":"HERO_BANNER", "prompt":"text-free organized car trunk", "negative_prompt":"text logo watermark",
            "text_policy":"NO_EMBEDDED_TEXT", "target":{"width":1024,"height":576,"aspect_ratio":"16:9"},
            "safe_zone":{"mobile_center_safe":True}, "brand":{"brand_name":"Cabin Tidy", "palette":"navy and sand"},
            "collection":{}, "reference_images":[], "output_count":3, "output_dir":str(tmp_path / "候補画像"),
            "request_context":{}}
    data.update(updates)
    return data


def test_health_capabilities_doctor_truthfully_report_nonconfigured_generator(tmp_path):
    assert bridge.capabilities()["generator"]["ready"] is False
    assert "LEGACY_CROP" in bridge.capabilities()["providers"]
    assert "LOCAL_GENERATOR" in bridge.capabilities()["providers"]
    diagnosis = bridge.doctor()
    assert "pillow" in diagnosis["checks"] and "numpy" in diagnosis["checks"] and "opencv" in diagnosis["checks"]


@pytest.mark.parametrize("asset_type,size", [("HERO_BANNER", (900, 500)), ("COLLECTION_SQUARE", (700, 700))])
def test_job_without_generator_returns_waiting_for_configuration(tmp_path, asset_type, size):
    value = job(tmp_path, asset_type=asset_type, target={"width":size[0],"height":size[1],"aspect_ratio":"1:1"})
    result = bridge.execute_job(value)
    assert result["status"] == "WAITING_FOR_CONFIGURATION"
    assert result["error"]["code"] == "GENERATOR_NOT_CONFIGURED"


def test_unicode_output_path_and_legacy_crop_reference(tmp_path):
    output = tmp_path / "출력 폴더" / "생성 후보"
    output.mkdir(parents=True)
    reference = tmp_path / "참고 이미지.png"; Image.new("RGB", (640, 360), "navy").save(reference)
    result = bridge.execute_job(job(tmp_path, asset_type="HERO_BANNER", reference_images=[str(reference)], output_dir=str(output),
                                    target={"width":640,"height":360,"aspect_ratio":"16:9"}, output_count=1))
    assert result["status"] == "SUCCEEDED"
    candidate = result["candidates"][0]
    assert Path(candidate["path"]).parent == output.resolve()
    assert candidate["source_type"] == "NON_GENERATIVE_DERIVATIVE"
    assert candidate["sha256"] == hashlib.sha256(Path(candidate["path"]).read_bytes()).hexdigest()


def test_output_path_escape_is_rejected(tmp_path):
    output = tmp_path / "requested"; output.mkdir()
    outside = tmp_path / "outside.png"; Image.new("RGB", (640, 360), "white").save(outside)
    class Escape(bridge.ImageProvider):
        name="FAKE_TEST_PROVIDER"; model="synthetic"
        def generate(self, value): return [{"path":str(outside),"technical_score":1}]
    result = bridge.execute_job(job(tmp_path, output_dir=str(output), target={"width":640,"height":360}, output_count=1), provider=Escape())
    assert result["status"] == "FAILED" and not result["candidates"]


def test_duplicate_hash_rejected_and_partial_candidate_failure(tmp_path):
    output = tmp_path / "out"; output.mkdir()
    one, two = output / "one.png", output / "two.png"
    Image.new("RGB", (640,360), "white").save(one); two.write_bytes(one.read_bytes())
    class Mixed(bridge.ImageProvider):
        name="FAKE_TEST_PROVIDER"; model="synthetic"
        def generate(self, value): return [{"path":str(one),"technical_score":1},{"path":str(two),"technical_score":0}]
    result=bridge.execute_job(job(tmp_path, output_dir=str(output), target={"width":640,"height":360}, output_count=2), provider=Mixed())
    assert result["status"] == "PARTIAL" and len(result["candidates"]) == 1
    assert "DUPLICATE_CANDIDATE_HASH_REJECTED" in result["warnings"]


def test_result_json_written_atomically_for_unicode_job(tmp_path):
    source=tmp_path / "작업.json"; destination=tmp_path / "결과.json"
    source.write_text(json.dumps(job(tmp_path), ensure_ascii=False), encoding="utf-8")
    assert bridge.main(["--job",str(source),"--result",str(destination)]) == 0
    data=json.loads(destination.read_text(encoding="utf-8"))
    assert data["job_id"] == "job-001" and data["status"] == "WAITING_FOR_CONFIGURATION"
    assert not list(tmp_path.glob(".결과.json.*.tmp"))


def test_job_schema_rejects_output_directory_escape_before_provider(tmp_path):
    bad=job(tmp_path, output_dir=str(tmp_path / ".." / "outside"))
    resolved, _ = bridge._validate_job(bad)
    assert resolved == (tmp_path.parent / "outside").resolve()

