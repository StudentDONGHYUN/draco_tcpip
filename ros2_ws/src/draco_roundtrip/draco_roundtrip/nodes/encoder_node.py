
#!/usr/bin/env python3
"""ROS 2 node for encoding PointCloud2 messages into Draco format."""

from __future__ import annotations

import queue
import sys
import threading
import time
import base64
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import rclpy
from draco_roundtrip.draco.encoder import EncoderOptions, EncodeResult, encode_points
from draco_roundtrip.msg import CompressedPointCloud  # Import custom message
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2


def to_xyz_array_from_pc2(msg: PointCloud2) -> np.ndarray:
    """Convert PointCloud2 msg to a numpy array."""
    try:
        arr = pc2.read_points_numpy(msg, field_names=["x", "y", "z"], skip_nans=True)
        arr = np.asarray(arr, dtype=np.float32)
        if arr.ndim == 1:
            if arr.size == 0:
                return np.empty((0, 3), dtype=np.float32)
            arr = arr.reshape((-1, 3))
        elif arr.shape[1] > 3:
            arr = arr[:, :3]
        return arr
    except Exception:
        xyz_list = []
        for p in pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True):
            try:
                x, y, z = float(p[0]), float(p[1]), float(p[2])
            except Exception:
                x, y, z = float(p["x"]), float(p["y"]), float(p["z"])
            xyz_list.append((x, y, z))
        if not xyz_list:
            return np.empty((0, 3), dtype=np.float32)
        return np.asarray(xyz_list, dtype=np.float32)


@dataclass(slots=True)
class EncodingJob:
    frame_name: str
    header: object  # std_msgs.msg.Header
    future: Future[EncodeResult]
    original_size: int


class EncoderNode(Node):
    """Node that subscribes to PointCloud2, encodes it, and publishes CompressedPointCloud."""

    def __init__(self) -> None:
        super().__init__("encoder_node")

        # Declare parameters
        self.declare_parameter("topic_name", "/sensing/lidar/top/pointcloud")
        self.declare_parameter("qos_best_effort", False)
        self.declare_parameter("prefix", "client")
        self.declare_parameter("cl", 8)
        self.declare_parameter("qp", 12)
        self.declare_parameter("qg", 10)
        self.declare_parameter("encoder_extra", [])
        self.declare_parameter("num_workers", None)
        self.declare_parameter("max_queue_size", 64)

        # Get parameters
        topic_name = self.get_parameter("topic_name").value
        qos_best_effort = self.get_parameter("qos_best_effort").value
        self.prefix = str(self.get_parameter("prefix").value)
        encoder_extra = self.get_parameter("encoder_extra").value
        extra_args = tuple(encoder_extra) if isinstance(encoder_extra, (list, tuple)) else ()
        self.encoder_options = EncoderOptions(
            compress_level=int(self.get_parameter("cl").value),
            position_quantization_bits=int(self.get_parameter("qp").value),
            generic_quantization_bits=int(self.get_parameter("qg").value),
            extra_args=extra_args,
        )
        num_workers_param = self.get_parameter("num_workers").value
        self.num_workers = int(num_workers_param) if num_workers_param is not None else None
        max_queue_size = int(self.get_parameter("max_queue_size").value)

        # ROS Publisher for compressed data
        qos = QoSProfile(
            depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE
        )
        self.pub_compressed = self.create_publisher(
            CompressedPointCloud, "/compressed_pointcloud", qos
        )

        # Inter-thread queues
        self._msg_queue: "queue.Queue[PointCloud2]" = queue.Queue(maxsize=max_queue_size)
        self._future_queue: "queue.Queue[EncodingJob]" = queue.Queue(maxsize=max_queue_size)

        # Subscriber for topic source
        sub_qos = QoSProfile(depth=max_queue_size, history=HistoryPolicy.KEEP_LAST)
        sub_qos.reliability = (
            ReliabilityPolicy.BEST_EFFORT if qos_best_effort else ReliabilityPolicy.RELIABLE
        )
        self.create_subscription(PointCloud2, topic_name, self._on_pointcloud_msg, sub_qos)
        self.get_logger().info(f"Listening for PointCloud2 messages on {topic_name}")

        # Threading setup
        self._stop_event = threading.Event()
        self._executor = ProcessPoolExecutor(max_workers=self.num_workers)
        self._encoder_thread = threading.Thread(target=self._run_encoder_loop, daemon=True)
        self._publisher_thread = threading.Thread(target=self._run_publisher_loop, daemon=True)

        self._encoder_thread.start()
        self._publisher_thread.start()

        # Metrics
        self._metrics = []
        self._start_time = time.monotonic()
        self._report_generated = False

    def _on_pointcloud_msg(self, msg: PointCloud2):
        try:
            self._msg_queue.put_nowait(msg)
        except queue.Full:
            self.get_logger().warning(
                f"Message queue is full (size={self._msg_queue.qsize()}), dropping frame."
            )

    def _run_encoder_loop(self) -> None:
        frame_idx = 0
        while not self._stop_event.is_set():
            try:
                msg = self._msg_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            frame_name = f"{self.prefix}_{frame_idx:010d}"
            try:
                pts_src = to_xyz_array_from_pc2(msg)
                if pts_src.size == 0:
                    self.get_logger().info(f"Skipping empty point cloud frame {frame_name}.")
                    continue
                original_size = pts_src.nbytes
                future = self._executor.submit(encode_points, pts_src, self.encoder_options)
                job = EncodingJob(
                    frame_name=frame_name,
                    header=msg.header,
                    future=future,
                    original_size=original_size,
                )
                self._future_queue.put(job)
                frame_idx += 1
            except Exception as exc:
                self.get_logger().error(f"ENCODE SUBMIT FAIL {frame_name}: {exc}")
                continue

    def _run_publisher_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._future_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                result = job.future.result()  # Wait for encoding to complete
                drc_bytes = result.encoded_data
                if not drc_bytes:
                    self.get_logger().warning(
                        f"Encoding resulted in empty data for frame {job.frame_name}. Skipping publish."
                    )
                    continue
                compression_time_ns = int(result.duration * 1e9)

                # Create and publish the custom message
                msg = CompressedPointCloud()
                msg.header = job.header
                msg.frame_name = job.frame_name
                msg.data = list(drc_bytes)
                msg.original_size = job.original_size
                msg.compression_time_ns = compression_time_ns
                self.pub_compressed.publish(msg)

                self.get_logger().info(f"Published compressed frame {job.frame_name} ({len(drc_bytes)} bytes)")

                # Store metrics
                self._metrics.append({
                    'frame_name': job.frame_name,
                    'original_size': job.original_size,
                    'compressed_size': len(drc_bytes),
                    'compression_time_ns': compression_time_ns,
                })

            except Exception as exc:
                self.get_logger().error(f"PUBLISH FAIL {job.frame_name}: {exc}")
                continue

    def _create_plot_base64(
        self, x_data, y_data, title, xlabel, ylabel, color='b'
    ) -> str:
        """Create a matplotlib plot and return it as a base64 encoded string."""
        try:
            fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
            ax.plot(x_data, y_data, marker='.', linestyle='-', color=color)
            ax.set_title(title, fontsize=16)
            ax.set_xlabel(xlabel, fontsize=12)
            ax.set_ylabel(ylabel, fontsize=12)
            ax.grid(True)
            fig.tight_layout()

            buf = BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            return base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception as e:
            self.get_logger().error(f"Failed to create plot '{title}': {e}")
            return ""

    def _generate_report(self):
        if self._report_generated or not self._metrics:
            return
        self._report_generated = True

        total_time = time.monotonic() - self._start_time
        num_frames = len(self._metrics)
        fps = num_frames / total_time if total_time > 0 else 0

        total_original_size = sum(m['original_size'] for m in self._metrics)
        total_compressed_size = sum(m['compressed_size'] for m in self._metrics)
        compression_ratio = total_original_size / total_compressed_size if total_compressed_size > 0 else 0
        avg_compression_time_ms = sum(m['compression_time_ns'] for m in self._metrics) / num_frames / 1e6 if num_frames > 0 else 0

        # --- Plotting ---
        frame_indices = [int(m['frame_name'].split('_')[-1]) for m in self._metrics]
        compression_times_ms = [m['compression_time_ns'] / 1e6 for m in self._metrics]
        comp_time_plot_b64 = self._create_plot_base64(
            frame_indices, compression_times_ms, 'Compression Time per Frame', 'Frame Sequence', 'Time (ms)', 'c'
        )

        # --- HTML Generation ---
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Encoder Performance Report</title>
    <style>
        body {{ font-family: sans-serif; margin: 2rem; background-color: #f4f7f9; color: #333; }}
        .container {{ max-width: 1000px; margin: auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #ecf0f1; }}
        .plot {{ margin-top: 2rem; text-align: center; }}
        img {{ max-width: 100%; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Encoder Performance Report</h1>
        <p><strong>Report Generated:</strong> {datetime.now().isoformat()}</p>
        
        <h2>Summary</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Frames Encoded</td><td>{num_frames}</td></tr>
            <tr><td>Total Duration</td><td>{total_time:.2f} s</td></tr>
            <tr><td>Average FPS</td><td>{fps:.2f}</td></tr>
            <tr><td>Average Compression Time</td><td>{avg_compression_time_ms:.3f} ms</td></tr>
            <tr><td>Average Compression Ratio</td><td>{compression_ratio:.2f} : 1</td></tr>
        </table>

        <h2>Per-Frame Analysis</h2>
        <div class="plot">
            <h2>Compression Time</h2>
            <img src="data:image/png;base64,{comp_time_plot_b64}" alt="Compression Time Plot">
        </div>
    </div>
</body>
</html>
"""

        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        report_file = log_dir / f"encoder_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_file.write_text(html_content)
        self.get_logger().info(f"Encoder report saved to {report_file}")

    def destroy_node(self) -> None:
        self.get_logger().info("Shutting down encoder node...")
        self._generate_report()
        self._stop_event.set()
        if self._encoder_thread.is_alive():
            self._encoder_thread.join(timeout=1.0)
        if self._publisher_thread.is_alive():
            self._publisher_thread.join(timeout=1.0)
        self._executor.shutdown(wait=True)
        super().destroy_node()


def main(argv=None):
    rclpy.init(args=argv)
    node = EncoderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
