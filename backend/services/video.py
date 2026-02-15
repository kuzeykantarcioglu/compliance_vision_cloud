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

MAX_KEYFRAME_WIDTH = 768      # For file uploads — higher detail
MAX_WEBCAM_WIDTH = 512        # For webcam chunks — speed over detail
WEBCAM_JPEG_QUALITY = 60      # Lower quality for webcam = smaller base64 = faster upload
MAX_WEBCAM_FRAMES = 2         # 2 frames is enough for short webcam chunks


def resize_and_encode(image_path: str, max_width: int = MAX_KEYFRAME_WIDTH) -> str:
    """Read a keyframe image, resize to max_width, return base64 JPEG string."""
    img = cv2.imread(image_path)
    if img is None:
        return ""
    return _encode_frame(img, max_width)


def _encode_frame(img, max_width: int = MAX_KEYFRAME_WIDTH, jpeg_quality: int = 85) -> str:
    """Resize a cv2 frame and return base64 JPEG string."""
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
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

    # If OpenCV can't read (e.g. WebM on some Windows builds), return empty
    # and let the caller handle conversion. Avoids paying the ffmpeg cost
    # when OpenCV can handle it natively (Linux, newer Windows).
    if total_frames <= 0 or not cap.isOpened():
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
            image_base64=_encode_frame(frame, max_width=MAX_WEBCAM_WIDTH, jpeg_quality=WEBCAM_JPEG_QUALITY),
        ))

    cap.release()
    logger.info(f"Quick sample: {len(keyframes)} frames from {duration:.1f}s video")
    return keyframes


def _try_convert_webm(file_path: str) -> str:
    """Convert WebM to MP4 using ffmpeg. Returns new path, or original on failure."""
    import subprocess
    import shutil

    if not file_path.lower().endswith(".webm"):
        return file_path

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = shutil.which("ffmpeg")

    if not ffmpeg_exe:
        logger.warning("No ffmpeg found — cannot convert WebM")
        return file_path

    mp4_path = file_path.rsplit(".", 1)[0] + ".mp4"
    try:
        subprocess.run(
            [ffmpeg_exe, "-y", "-i", file_path, "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "23", "-an", mp4_path],
            capture_output=True, timeout=30, check=True,
        )
        logger.info(f"Converted WebM → MP4: {mp4_path}")
        return mp4_path
    except Exception as e:
        logger.warning(f"WebM→MP4 conversion failed: {e}")
        return file_path


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
        # Try OpenCV directly first (avoids ffmpeg conversion overhead)
        keyframes = _quick_sample(file_path, vid_keyframes_dir)
        # Fallback: if OpenCV couldn't read it (e.g. WebM on Windows), convert first
        if not keyframes and file_path.lower().endswith(".webm"):
            logger.info("OpenCV couldn't read WebM, converting to MP4...")
            converted = _try_convert_webm(file_path)
            if converted != file_path:
                video_id = generate_video_id(converted)
                keyframes = _quick_sample(converted, vid_keyframes_dir)
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
