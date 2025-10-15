
## Build, Lint, and Test

- **Build:** This is a ROS2 workspace. Build with `colcon build --symlink-install`. Source the workspace with `source install/setup.bash`.
- **Lint:** Ruff is used for linting. Run with `ruff check .`.
- **Test:** Pytest is used for testing.
  - Run all tests: `pytest`
  - Run a single test file: `pytest path/to/test_file.py`
  - Run a single test function: `pytest path/to/test_file.py::test_name`

## Architecture

This repository contains a ROS2 workspace for streaming 3D point cloud data, primarily for SLAM applications.

- **`draco_roundtrip`**: The core package. It implements a client-server system for compressing point clouds with Draco, streaming them over a custom TCP protocol, and decompressing them.
  - Important modules: `net/protocol.py` (custom TCP protocol), `nodes/stream_client.py`, `nodes/stream_server.py`.
- **`draco_tools`**: Contains offline utilities for processing point cloud data.
- **`slam_stream_bridge`**: Integrates the streaming pipeline with SLAM algorithms like RTAB-Map and HDL Graph SLAM.

## Code Style

- **Formatting:** Standard Python PEP 8. Use `ruff format .` to format.
- **Imports:** Grouped and sorted: 1. standard library, 2. third-party, 3. project-specific.
- **Naming:** `snake_case` for variables/functions, `PascalCase` for classes.
- **Typing:** Add type hints to all new functions and methods.
- **Error Handling:** Use specific exception types. Avoid broad `except Exception:`.
