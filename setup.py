"""

Setup.py for scpi_project

"""

import os
from setuptools import setup, find_packages


def read(rel_path):
    """ Read data from the file """
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, rel_path), 'r') as file:
        return file.read()


def get_version(rel_path):
    """ Parse version from the file """
    for line in read(rel_path).splitlines():
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]

    raise RuntimeError("Unable to find version string.")


long_description = read('README.md')

setup(name='scpi_project',
      version=get_version('scpi_project/__init__.py'),
      description='SCPI instrument driver',
      long_description=long_description,
      url='',
      author='Keith Gough',
      author_email='krgough@gmail.com',
      license='MIT',
      packages=find_packages(),
      install_requires=[
          'tqdm',
      ],
      zip_safe=False)
