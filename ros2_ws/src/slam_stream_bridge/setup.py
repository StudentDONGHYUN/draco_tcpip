from glob import glob
import os # 추가
from setuptools import find_packages, setup

package_name = 'slam_stream_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(include=[package_name, package_name + '.*']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob(package_name + '/launch/*.py')),
        (os.path.join('share', package_name, 'configs'), glob(os.path.join('configs', '*.yaml'))),
        (os.path.join('share', package_name, 'urdf'), glob(os.path.join('urdf', '*.urdf'))),
    ],
    install_requires=['setuptools'],
    zip_safe=False,
    maintainer='DONGHYUN',
    maintainer_email='agfee104@outlook.kr',
    description='Launch files bridging SLAM pipelines with Draco streaming utilities.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'time_jump_reset = slam_stream_bridge.nodes.time_jump_reset:main',
            'rtabmap_feedback_loop = slam_stream_bridge.nodes.rtabmap_feedback_loop:main',
        ],
    },
)
