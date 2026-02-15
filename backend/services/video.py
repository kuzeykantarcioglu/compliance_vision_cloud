"""Video processing service.

Wraps scene_detection.py and adds:
  - Keyframe resizing (max 512px wide) for VLM cost control
  - Base64 encoding for API transport
  - Clean integration with Pydantic schemas
"""

import os
import sys
import cv2
import base64

# Add project root to path so we can import scene_detection
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scene_detection import (
    detect_significant_changes,
    get_video_metadata,
    generate_video_id,
)
from backend.models.schemas import KeyframeData, VideoProcessingResult


MAX_KEYFRAME_WIDTH = 512  # Resize keyframes before sending to VLM


def resize_and_encode(image_path: str, max_width: int = MAX_KEYFRAME_WIDTH) -> str:
    """Read a keyframe image, resize to max_width, return base64 JPEG string."""
    img = cv2.imread(image_path)
    if img is None:
        return ""

    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        new_w = max_width
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    _, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


def process_video(
    file_path: str,
    keyframes_dir: str = "keyframes",
    sample_interval: float = 0.3,
    change_threshold: float = 0.10,
    min_change_interval: float = 0.5,
    max_gap: float = 10.0,
) -> VideoProcessingResult:
    """Run change detection on a video file and return structured results.

    Args:
        file_path: Path to the uploaded video file.
        keyframes_dir: Where to save extracted keyframe images.
        sample_interval: Seconds between sampled frames.
        change_threshold: Sensitivity (0-1, lower = more sensitive).
        min_change_interval: Min seconds between change captures.
        max_gap: Max seconds without a keyframe.

    Returns:
        VideoProcessingResult with video_id, metadata, and keyframes (including base64).
    """
    video_id = generate_video_id(file_path)
    metadata = get_video_metadata(file_path)

    # Run per-video keyframes dir to avoid collisions
    vid_keyframes_dir = os.path.join(keyframes_dir, video_id)
    os.makedirs(vid_keyframes_dir, exist_ok=True)

    events = detect_significant_changes(
        video_path=file_path,
        sample_interval=sample_interval,
        change_threshold=change_threshold,
        min_change_interval=min_change_interval,
        max_gap=max_gap,
        keyframes_dir=vid_keyframes_dir,
    )

    # Convert events to KeyframeData with base64 images
    keyframes = []
    for evt in events:
        kf_path = evt["keyframe_path"]
        image_b64 = resize_and_encode(kf_path)

        keyframes.append(KeyframeData(
            timestamp=evt["timestamp"],
            frame_number=evt["frame_number"],
            change_score=evt["change_score"],
            trigger=evt["trigger"],
            keyframe_path=kf_path,
            image_base64=image_b64,
        ))

    metadata["total_change_events"] = len(keyframes)

    return VideoProcessingResult(
        video_id=video_id,
        metadata=metadata,
        keyframes=keyframes,
    )
