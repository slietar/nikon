from setuptools import setup

setup(
  name="nikon",
  version="0.0.0",

  description="Control of the Nikon Ti2-E microscope",
  url="https://github.com/slietar/okolab",

  python_requires=">=3.10",
  install_requires=[
    "pyusb==1.2.1"
  ]
)
