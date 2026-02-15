#!/usr/bin/env python3
"""
Significant Change Detection for Video Compliance Monitoring

Detects meaningful visual changes in video (file or live webcam):
  - Person entering/leaving frame
  - Object appearing/disappearing
  - Posture or action changes
  - Environmental changes (door opening, lighting shift, etc.)

Performance features:
  - Sequential frame reading (no seeking) for ~5-10x faster file processing
  - Early termination: skip expensive structural diff when histogram says "no change"
  - Threaded pipeline: read → detect → write keyframes in parallel
  - Streaming mode for real-time webcam processing
  - Cached pre-processed frames to avoid redundant resize/convert
"""

import os
import cv2
import json
import time
import hashlib
import logging
import threading
import numpy as np
from queue import Queue, Empty
from datetime import datetime
from typing import Optional, Callable
import argparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_video_id(video_path):
    """Generate unique video ID from file path and size."""
    file_size = os.path.getsize(video_path)
    content = f"{video_path}_{file_size}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def get_video_metadata(video_path):
    """Extract basic video metadata."""
    cap = cv2.VideoCapture(video_path)

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps > 0 else 0

    metadata = {
        "url": f"local://{os.path.abspath(video_path)}",
        "filename": os.path.basename(video_path),
        "duration": round(duration, 2),
        "fps": fps,
        "width": width,
        "height": height,
        "total_frames": frame_count,
        "resolution": f"{width}x{height}",
    }

    if height > 0:
        ratio = width / height
        if abs(ratio - 16 / 9) < 0.1:
            metadata["aspect_ratio"] = "16:9"
        elif abs(ratio - 4 / 3) < 0.1:
            metadata["aspect_ratio"] = "4:3"
        elif abs(ratio - 1) < 0.1:
            metadata["aspect_ratio"] = "1:1"
        else:
            metadata["aspect_ratio"] = f"{width}:{height}"

    cap.release()
    return metadata


# ---------------------------------------------------------------------------
# Frame comparison — optimized
# ---------------------------------------------------------------------------

RESIZE_DIM = 256  # Pre-process target size for comparisons


def preprocess_frame(frame):
    """Resize + convert a frame for comparison. Cache this to avoid recomputing.

    Returns (small_gray_blurred, hsv_histogram).
    """
    small = cv2.resize(frame, (RESIZE_DIM, RESIZE_DIM))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)

    return blurred, hist


def compute_change_score(prep_curr, prep_prev, early_exit_corr=0.95):
    """Compare two pre-processed frames. Returns change score 0-1.

    Uses early termination: if histogram correlation is very high (> early_exit_corr),
    skip the more expensive structural diff entirely. This saves ~50% of compute
    on frames where nothing changed (the common case for surveillance footage).

    Args:
        prep_curr: (gray_blurred, histogram) from preprocess_frame()
        prep_prev: (gray_blurred, histogram) from preprocess_frame()
        early_exit_corr: Correlation threshold above which we skip structural diff.

    Returns:
        float: Change score 0-1 (higher = more change).
    """
    gray_curr, hist_curr = prep_curr
    gray_prev, hist_prev = prep_prev

    # --- Stage 1: Histogram correlation (cheap) ---
    hist_corr = cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)
    hist_change = 1.0 - max(hist_corr, 0.0)

    # Early exit: if histogram says nearly identical, don't bother with pixel diff.
    # This skips ~80% of frames in typical surveillance footage.
    if hist_corr > early_exit_corr:
        return round(hist_change * 0.5, 4)  # Scale down since we only used one signal

    # --- Stage 2: Structural pixel diff (more expensive, only when needed) ---
    diff = cv2.absdiff(gray_prev, gray_curr)
    changed_pixels = np.count_nonzero(diff > 25)
    total_pixels = RESIZE_DIM * RESIZE_DIM
    struct_change = changed_pixels / total_pixels

    combined = 0.5 * hist_change + 0.5 * struct_change
    return round(float(combined), 4)


# ---------------------------------------------------------------------------
# Threaded keyframe writer
# ---------------------------------------------------------------------------

class KeyframeWriter:
    """Writes keyframe images to disk in a background thread.

    cv2.imwrite is synchronous disk I/O — we don't want it blocking the
    detection loop. This queues writes and processes them in a separate thread.
    """

    def __init__(self):
        self._queue = Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def write(self, path, frame):
        """Queue a keyframe for writing. Non-blocking."""
        self._queue.put((path, frame.copy()))

    def _worker(self):
        while True:
            try:
                path, frame = self._queue.get(timeout=1.0)
                cv2.imwrite(path, frame)
                self._queue.task_done()
            except Empty:
                continue

    def flush(self):
        """Block until all queued writes are finished."""
        self._queue.join()


# ---------------------------------------------------------------------------
# Core: ChangeDetector (stateful, supports both file and streaming)
# ---------------------------------------------------------------------------

class ChangeDetector:
    """Stateful change detector that works for both file and real-time modes.

    Holds the comparison state (previous frame, histogram, timing) so it can
    process frames one at a time from any source.
    """

    def __init__(
        self,
        change_threshold=0.10,
        min_change_interval=0.5,
        max_gap=10.0,
        keyframes_dir="keyframes",
        on_change: Optional[Callable] = None,
    ):
        """
        Args:
            change_threshold:    Score 0-1 above which = significant change.
            min_change_interval: Min seconds between change captures (debounce).
            max_gap:             Max seconds without a keyframe.
            keyframes_dir:       Where to save keyframe images.
            on_change:           Optional callback: on_change(event_dict) called
                                 immediately when a change is detected. Useful for
                                 real-time: pipe events to VLM without waiting for
                                 the full video to finish.
        """
        self.change_threshold = change_threshold
        self.min_change_interval = min_change_interval
        self.max_gap = max_gap
        self.keyframes_dir = keyframes_dir
        self.on_change = on_change

        os.makedirs(keyframes_dir, exist_ok=True)

        # State
        self._prev_prep = None      # (gray_blurred, histogram) of last captured keyframe
        self._prev_frame = None     # Raw frame of last captured keyframe (for saving)
        self._last_capture_time = -999.0
        self._events = []
        self._writer = KeyframeWriter()

    @property
    def events(self):
        return list(self._events)

    def process_frame(self, frame, timestamp, frame_number=0):
        """Process a single frame. Returns event dict if change detected, else None.

        This is the core method — call it from any source:
          - File reader loop
          - Webcam capture loop
          - WebSocket frame receiver
        """
        prep = preprocess_frame(frame)

        # --- First frame: always capture ---
        if self._prev_prep is None:
            return self._capture(frame, prep, timestamp, frame_number, 1.0, "first")

        # --- Compute change score ---
        score = compute_change_score(prep, self._prev_prep)
        time_since_last = timestamp - self._last_capture_time

        trigger = None
        if score >= self.change_threshold and time_since_last >= self.min_change_interval:
            trigger = "change"
        elif time_since_last >= self.max_gap:
            trigger = "max_gap"

        if trigger:
            return self._capture(frame, prep, timestamp, frame_number, score, trigger)

        return None

    def _capture(self, frame, prep, timestamp, frame_number, score, trigger):
        """Record a change event, save keyframe, fire callback."""
        idx = len(self._events)
        kf_path = os.path.join(self.keyframes_dir, f"change_{idx:04d}.jpg")

        # Queue the write — doesn't block detection loop
        self._writer.write(kf_path, frame)

        event = {
            "event_index": idx,
            "timestamp": round(timestamp, 2),
            "frame_number": frame_number,
            "change_score": score,
            "trigger": trigger,
            "keyframe_path": kf_path,
        }
        self._events.append(event)

        # Update state
        self._prev_prep = prep
        self._prev_frame = frame
        self._last_capture_time = timestamp

        # Fire callback for real-time consumers (e.g. VLM pipeline)
        if self.on_change:
            self.on_change(event)

        return event

    def finalize(self):
        """Flush pending keyframe writes. Call when done processing."""
        self._writer.flush()

    def reset(self):
        """Reset state for a new video/stream. Keeps config, clears events."""
        self._prev_prep = None
        self._prev_frame = None
        self._last_capture_time = -999.0
        self._events = []


# ---------------------------------------------------------------------------
# File mode: threaded reader → detector pipeline
# ---------------------------------------------------------------------------

def _frame_reader_thread(cap, sample_step, out_queue, stop_event):
    """Read frames sequentially (no seeking!) and push to queue.

    Sequential cap.read() is 5-10x faster than cap.set(POS_FRAMES) + read()
    because H.264/H.265 decoders maintain state between sequential frames.
    Seeking forces the decoder to find the nearest I-frame and decode forward.
    """
    frame_idx = 0
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_step == 0:
            out_queue.put((frame_idx, frame))

        frame_idx += 1

    out_queue.put(None)  # Sentinel: no more frames


def detect_significant_changes(
    video_path,
    sample_interval=0.3,
    change_threshold=0.10,
    min_change_interval=0.5,
    max_gap=10.0,
    keyframes_dir="keyframes",
    on_change: Optional[Callable] = None,
):
    """Detect significant visual changes in a video file.

    Uses a threaded pipeline:
      Thread 1 (reader):   cap.read() sequentially, skip non-sampled frames, queue sampled frames
      Thread 0 (main):     dequeue frames, run change detection, record events

    Keyframe writes are also threaded via KeyframeWriter.

    Args:
        video_path:          Path to input video file.
        sample_interval:     How often to sample frames, in seconds.
        change_threshold:    Change score 0-1 above which = significant change.
        min_change_interval: Min seconds between change captures.
        max_gap:             Max seconds without a keyframe.
        keyframes_dir:       Where to save keyframe images.
        on_change:           Optional callback fired on each change event.

    Returns:
        list[dict]: Change events with timestamp, score, trigger, keyframe_path.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    sample_step = max(1, int(fps * sample_interval))

    logger.info(f"Analyzing video: {video_path}")
    logger.info(f"  Duration: {duration:.1f}s | FPS: {fps:.1f} | Frames: {total_frames}")
    logger.info(f"  Sampling every {sample_interval}s ({sample_step} frames) | Threshold: {change_threshold}")
    logger.info(f"  Min interval: {min_change_interval}s | Max gap: {max_gap}s")
    logger.info(f"  Mode: threaded pipeline (reader thread + detector + async writer)")

    detector = ChangeDetector(
        change_threshold=change_threshold,
        min_change_interval=min_change_interval,
        max_gap=max_gap,
        keyframes_dir=keyframes_dir,
        on_change=on_change,
    )

    # --- Start reader thread ---
    frame_queue = Queue(maxsize=30)  # Buffer ~30 sampled frames
    stop_event = threading.Event()
    reader = threading.Thread(
        target=_frame_reader_thread,
        args=(cap, sample_step, frame_queue, stop_event),
        daemon=True,
    )
    reader.start()

    t_start = time.perf_counter()
    frames_processed = 0

    # --- Main loop: consume frames from reader thread ---
    while True:
        item = frame_queue.get()
        if item is None:
            break

        frame_idx, frame = item
        timestamp = frame_idx / fps

        event = detector.process_frame(frame, timestamp, frame_idx)
        if event:
            tag = event["trigger"].upper().ljust(7)
            logger.info(f"  [{tag}]  t={timestamp:7.2f}s  score={event['change_score']:.4f}  frame={frame_idx}")

        frames_processed += 1

    # --- Capture last frame if not already captured ---
    last_frame_idx = total_frames - 1
    if last_frame_idx > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, last_frame_idx)
        ret, frame = cap.read()
        if ret:
            events = detector.events
            if not events or events[-1]["frame_number"] != last_frame_idx:
                ts = last_frame_idx / fps
                event = detector.process_frame(frame, ts, last_frame_idx)
                if event:
                    # Force it as "last" trigger
                    event["trigger"] = "last"
                    logger.info(f"  [LAST   ]  t={ts:7.2f}s  frame={last_frame_idx}")

    cap.release()
    stop_event.set()
    reader.join(timeout=2.0)
    detector.finalize()  # Flush pending keyframe writes

    elapsed = time.perf_counter() - t_start
    events = detector.events

    logger.info(f"Total change events: {len(events)}")
    logger.info(f"Frames sampled: {frames_processed}")
    logger.info(f"Processing time: {elapsed:.2f}s ({frames_processed / max(elapsed, 0.001):.0f} sampled frames/sec)")

    return events


# ---------------------------------------------------------------------------
# Streaming mode: for real-time webcam / live feed
# ---------------------------------------------------------------------------

class StreamingDetector:
    """Real-time change detection for webcam or live video feeds.

    Usage:
        detector = StreamingDetector(
            source=0,  # webcam index, or RTSP URL
            on_change=lambda evt: send_to_vlm(evt),
        )
        detector.start()      # non-blocking, runs in background
        ...
        detector.stop()
        print(detector.events)

    The on_change callback fires immediately when a significant change is
    detected — use this to pipe keyframes to the VLM in real-time without
    waiting for the stream to end.

    Internally uses two threads:
      Thread 1 (grabber):  Continuously grabs frames, keeps only the latest
                           in a ring buffer (no queue buildup if processing is slow)
      Thread 2 (detector): Samples from the ring buffer at sample_interval,
                           runs change detection, fires callbacks
    """

    def __init__(
        self,
        source=0,
        sample_interval=0.3,
        change_threshold=0.10,
        min_change_interval=0.5,
        max_gap=10.0,
        keyframes_dir="keyframes",
        on_change: Optional[Callable] = None,
    ):
        self.source = source
        self.sample_interval = sample_interval
        self.on_change = on_change

        self._detector = ChangeDetector(
            change_threshold=change_threshold,
            min_change_interval=min_change_interval,
            max_gap=max_gap,
            keyframes_dir=keyframes_dir,
            on_change=on_change,
        )

        # Ring buffer: always holds the latest frame
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._frame_number = 0

        self._stop_event = threading.Event()
        self._grabber_thread = None
        self._detector_thread = None
        self._start_time = None

    @property
    def events(self):
        return self._detector.events

    def start(self):
        """Start background capture + detection. Non-blocking."""
        self._stop_event.clear()
        self._start_time = time.time()
        self._grabber_thread = threading.Thread(target=self._grabber_loop, daemon=True)
        self._detector_thread = threading.Thread(target=self._detector_loop, daemon=True)
        self._grabber_thread.start()
        self._detector_thread.start()
        logger.info(f"Streaming detector started (source={self.source}, interval={self.sample_interval}s)")

    def stop(self):
        """Stop capture + detection. Blocks until threads finish."""
        self._stop_event.set()
        if self._grabber_thread:
            self._grabber_thread.join(timeout=3.0)
        if self._detector_thread:
            self._detector_thread.join(timeout=3.0)
        self._detector.finalize()
        logger.info(f"Streaming detector stopped. {len(self.events)} events captured.")

    def _grabber_loop(self):
        """Continuously grab frames, store only the latest (ring buffer of 1).

        If detection is slower than capture, we just drop intermediate frames.
        This prevents memory buildup and ensures we always process the
        most recent view of the scene.
        """
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            logger.error(f"Could not open video source: {self.source}")
            return

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            with self._frame_lock:
                self._latest_frame = frame
                self._frame_number += 1

        cap.release()

    def _detector_loop(self):
        """Sample from ring buffer at fixed intervals, run change detection."""
        while not self._stop_event.is_set():
            # Wait for next sample interval
            time.sleep(self.sample_interval)

            with self._frame_lock:
                frame = self._latest_frame
                frame_num = self._frame_number

            if frame is None:
                continue

            timestamp = time.time() - self._start_time
            event = self._detector.process_frame(frame, timestamp, frame_num)

            if event:
                tag = event["trigger"].upper().ljust(7)
                logger.info(f"  [LIVE {tag}]  t={timestamp:7.2f}s  score={event['change_score']:.4f}")


# ---------------------------------------------------------------------------
# Persistence (unchanged)
# ---------------------------------------------------------------------------

def save_video_data(video_id, metadata):
    """Save video metadata to JSON file."""
    os.makedirs("data/videos", exist_ok=True)
    filepath = f"data/videos/{video_id}.json"

    metadata.update({
        "id": video_id,
        "processing_status": "complete",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    })

    with open(filepath, "w") as f:
        json.dump(metadata, f, indent=2)

    return filepath


def save_change_events(video_id, events):
    """Save change events to JSON file."""
    os.makedirs("data/changes", exist_ok=True)
    filepath = f"data/changes/{video_id}_changes.json"

    output = []
    for evt in events:
        entry = dict(evt)
        entry["id"] = f"evt_{evt['event_index']:04d}"
        entry["created_at"] = datetime.now().isoformat()
        if "keyframe_path" in entry:
            entry["keyframe_url"] = entry.pop("keyframe_path")
        output.append(entry)

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)

    return filepath


def load_video_data(video_id):
    """Load video + change event data from JSON files."""
    video_path = f"data/videos/{video_id}.json"
    changes_path = f"data/changes/{video_id}_changes.json"

    data = {}

    if os.path.exists(video_path):
        with open(video_path, "r") as f:
            data["video"] = json.load(f)

    if os.path.exists(changes_path):
        with open(changes_path, "r") as f:
            data["changes"] = json.load(f)

    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect significant visual changes in video for compliance monitoring"
    )
    parser.add_argument(
        "video_path",
        help="Path to video file, or 'webcam' / 'webcam:0' for live camera"
    )
    parser.add_argument(
        "--sample-interval", type=float, default=0.3,
        help="Frame sampling interval in seconds (default: 0.3)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.10,
        help="Change detection threshold 0-1 (default: 0.10, lower = more sensitive)"
    )
    parser.add_argument(
        "--min-interval", type=float, default=0.5,
        help="Minimum seconds between change captures (default: 0.5)"
    )
    parser.add_argument(
        "--max-gap", type=float, default=10.0,
        help="Max seconds without a keyframe (default: 10.0)"
    )
    parser.add_argument(
        "--keyframes", default="keyframes",
        help="Output directory for keyframes (default: keyframes)"
    )
    parser.add_argument(
        "--duration", type=float, default=60.0,
        help="For webcam mode: how many seconds to capture (default: 60)"
    )

    args = parser.parse_args()

    # --- Webcam / streaming mode ---
    if args.video_path.startswith("webcam"):
        parts = args.video_path.split(":")
        source = int(parts[1]) if len(parts) > 1 else 0

        print(f"Starting webcam capture (source={source}, duration={args.duration}s)")
        print(f"Press Ctrl+C to stop early.\n")

        detector = StreamingDetector(
            source=source,
            sample_interval=args.sample_interval,
            change_threshold=args.threshold,
            min_change_interval=args.min_interval,
            max_gap=args.max_gap,
            keyframes_dir=args.keyframes,
        )

        detector.start()
        try:
            time.sleep(args.duration)
        except KeyboardInterrupt:
            print("\nStopping...")
        detector.stop()

        events = detector.events
        if events:
            video_id = hashlib.md5(f"webcam_{time.time()}".encode()).hexdigest()[:12]
            changes_file = save_change_events(video_id, events)
            print(f"\n  Change events saved: {changes_file}")

        print(f"\nEvent Timeline:")
        for evt in events:
            tag = evt["trigger"].upper().ljust(7)
            print(f"  [{tag}] t={evt['timestamp']:7.2f}s  score={evt['change_score']:.4f}")

        return

    # --- File mode ---
    if not os.path.exists(args.video_path):
        print(f"Error: Video file not found: {args.video_path}")
        return

    video_id = generate_video_id(args.video_path)
    print(f"Video ID: {video_id}\n")

    metadata = get_video_metadata(args.video_path)
    print("Video Metadata:")
    for key, value in metadata.items():
        print(f"  {key}: {value}")
    print()

    events = detect_significant_changes(
        args.video_path,
        sample_interval=args.sample_interval,
        change_threshold=args.threshold,
        min_change_interval=args.min_interval,
        max_gap=args.max_gap,
        keyframes_dir=args.keyframes,
    )

    metadata["total_change_events"] = len(events)

    # Save
    print("\nSaving data...")
    video_file = save_video_data(video_id, metadata)
    changes_file = save_change_events(video_id, events)
    print(f"  Video metadata: {video_file}")
    print(f"  Change events:  {changes_file}")

    # Summary
    change_triggers = sum(1 for e in events if e["trigger"] == "change")
    gap_triggers = sum(1 for e in events if e["trigger"] == "max_gap")
    bookend_triggers = sum(1 for e in events if e["trigger"] in ("first", "last"))

    print(f"\nDone!")
    print(f"  Total keyframes:   {len(events)}")
    print(f"    Change events:   {change_triggers}")
    print(f"    Gap fills:       {gap_triggers}")
    print(f"    Bookends:        {bookend_triggers}")
    print(f"  Keyframes saved:   {args.keyframes}/")
    print(f"  Video duration:    {metadata['duration']:.1f}s")

    print(f"\nEvent Timeline:")
    for evt in events:
        tag = evt["trigger"].upper().ljust(7)
        print(f"  [{tag}] t={evt['timestamp']:7.2f}s  score={evt['change_score']:.4f}")


if __name__ == "__main__":
    main()
