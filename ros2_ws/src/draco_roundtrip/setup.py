from setuptools import find_packages, setup

package_name = 'draco_roundtrip'

setup(
    name=package_name,
    version='0.1.0',
    install_requires=['setuptools', 'ament_index_python', 'DracoPy'],
    zip_safe=False,
    maintainer='GodokSa',
    maintainer_email='ppakdone@gmail.com',
    description='ROS 2 client/server nodes for Draco point cloud roundtrip experiments.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'encoder_node = draco_roundtrip.nodes.encoder_node:main',
            'sender_node = draco_roundtrip.nodes.sender_node:main',
            'stream_server = draco_roundtrip.nodes.stream_server:main',
            'stream_monitor = draco_roundtrip.tools.monitor:main',
            'stream_replay = draco_roundtrip.tools.replay:main',
            'ply_saver = draco_roundtrip.io.bag_recorder:main',
        ],
    },
)
