# pytodo-qt

A simple to-do list program.

## Description

A small cross-platform application to manage multiple to-do lists written in Python 3 and PyQt6

## Getting started

- Install a recent version of Python, needs **at least** version *3.8*
- For a package install you will need `pip` or `pipx`
- For a manual install you will need `git` and the python modules `setuptools`, `wheel`, `build` and `PyQt6`
  You can install these via your package manager or via `pip`

## Installation

- Install a package. **Recommended**.

It can be installed from PyPi via pip or preferably pipx, all three of these methods should work

    $ pipx install pytodo-qt       # for a local virtualenv install
    $ pip install pytodo-qt        # for a systemwide install
    $ pip install --user pytodo-qt # for a user local install

- Manual install

It can be installed by cloning the git repository and building the package:

    $ git clone https://github.com/berrym/pytodo-qt.git
    $ cd pytodo-qt
    $ python3 -m venv /path/to/pytodo-qt/venv
    $ sh /path/to/pytodo-qt/venv/bin/activate  # for linux/unix, activate the appropriate script for your os
    $ python3 -m build
    $ /path/to/pytodo-qt/venv/bin/pip install .

### Executing program

If you installed a package then a script named `todo` was installed

    $ todo  # launches the application

If you followed the manual local build instructions

    $ /path/to/pytodo-qt/venv/bin/todo  # launches the application

## Help

    $ todo --help

## Copyright

Copyright 2024 Michael Berry <trismegustis@gmail.com>

## Latest release

- v0.2.5

## License

This project is licensed under the GNU General Public License version 3, or at your option any later version.
See the COPYING file included in the git repository.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
