cmake_minimum_required(VERSION 3.8)
project(draco_roundtrip)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/CompressedPointCloud.msg"
  DEPENDENCIES std_msgs
)

install(
  DIRECTORY draco_roundtrip
  DESTINATION ${PYTHON_INSTALL_DIR}
  PATTERN "__pycache__" EXCLUDE
)

install(
  PROGRAMS
    scripts/encoder_node
    scripts/sender_node
    scripts/stream_server
    scripts/stream_monitor
    scripts/stream_replay
    scripts/ply_saver
    scripts/tf_fallback
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY urdf
  DESTINATION share/${PROJECT_NAME}
)

install(
  FILES draco_roundtrip/configs/qos_override.yaml
  DESTINATION share/${PROJECT_NAME}/config
)

install(
  FILES resource/${PROJECT_NAME}
  DESTINATION share/ament_index/resource_index/packages
)

install(
  FILES package.xml
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
