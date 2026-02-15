"""Video processing service.

Two modes:
  - Short videos (<15s, webcam chunks): fast interval sampling (no change detection)
  - Long videos (≥15s, file uploads): full change detection pipeline

Both modes resize to max 768px wide and encode as base64 JPEG for VLM.
"""

import os
import sys
import logging
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

logger = logging.getLogger(__name__)

MAX_KEYFRAME_WIDTH = 768  # Larger for better VLM detail recognition
MAX_WEBCAM_FRAMES = 3     # Cap frames per webcam chunk for speed


def resize_and_encode(image_path: str, max_width: int = MAX_KEYFRAME_WIDTH) -> str:
    """Read a keyframe image, resize to max_width, return base64 JPEG string."""
    img = cv2.imread(image_path)
    if img is None:
        return ""
    return _encode_frame(img, max_width)


def _encode_frame(img, max_width: int = MAX_KEYFRAME_WIDTH) -> str:
    """Resize a cv2 frame and return base64 JPEG string."""
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode("utf-8")


def _quick_sample(file_path: str, keyframes_dir: str, max_frames: int = MAX_WEBCAM_FRAMES) -> list[KeyframeData]:
    """Fast interval sampling for short webcam chunks. No change detection.

    Samples frames at evenly-spaced intervals. Much faster and more reliable
    than change detection for 2-8s webcam recordings.
    """
    cap = cv2.VideoCapture(file_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    if total_frames <= 0:
        cap.release()
        return []

    # Pick evenly-spaced frame indices
    if total_frames <= max_frames:
        # Very short — just grab a few spread out
        indices = [0, total_frames // 2, max(0, total_frames - 2)]
        indices = sorted(set(i for i in indices if i < total_frames))[:max_frames]
    else:
        step = total_frames / (max_frames + 1)
        indices = [int(step * (i + 1)) for i in range(max_frames)]
        # Always include a frame near the start
        if indices[0] > int(fps):
            indices[0] = int(fps * 0.5)

    keyframes = []
    os.makedirs(keyframes_dir, exist_ok=True)

    for idx, frame_idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        ts = frame_idx / fps
        kf_path = os.path.join(keyframes_dir, f"sample_{idx:04d}.jpg")
        cv2.imwrite(kf_path, frame)

        keyframes.append(KeyframeData(
            timestamp=round(ts, 2),
            frame_number=frame_idx,
            change_score=0.0,
            trigger="sample",
            keyframe_path=kf_path,
            image_base64=_encode_frame(frame),
        ))

    cap.release()
    logger.info(f"Quick sample: {len(keyframes)} frames from {duration:.1f}s video")
    return keyframes


def process_video(
    file_path: str,
    keyframes_dir: str = "keyframes",
    sample_interval: float = 0.3,
    change_threshold: float = 0.10,
    min_change_interval: float = 0.5,
    max_gap: float = 10.0,
) -> VideoProcessingResult:
    """Process a video file and extract keyframes.

    Short videos (<15s, webcam chunks) use fast interval sampling.
    Long videos use full change detection for efficiency.
    """
    video_id = generate_video_id(file_path)
    metadata = get_video_metadata(file_path)
    duration = metadata.get("duration", 0.0)

    vid_keyframes_dir = os.path.join(keyframes_dir, video_id)
    os.makedirs(vid_keyframes_dir, exist_ok=True)

    if duration < 15.0:
        # --- Short video (webcam chunk): fast interval sampling ---
        keyframes = _quick_sample(file_path, vid_keyframes_dir)
    else:
        # --- Long video (file upload): full change detection ---
        events = detect_significant_changes(
            video_path=file_path,
            sample_interval=sample_interval,
            change_threshold=change_threshold,
            min_change_interval=min_change_interval,
            max_gap=max_gap,
            keyframes_dir=vid_keyframes_dir,
        )
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
