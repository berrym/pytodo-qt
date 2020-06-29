from setuptools import setup

setup(
    name="To-Do",
    version="0.1.1",
    packages=["gui", "net", "core", "crypto"],
    url="https://github.com/berrym/pytodo",
    license="GPLv3",
    author="Michael Berry",
    author_email="trismegustis@gmail.com",
    description="A simple To-Do list app",
    install_requires=["PyQt5", "pycryptodomex"],
)
