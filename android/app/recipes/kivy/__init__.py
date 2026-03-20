"""
Custom kivy recipe: download from PyPI sdist (has pre-generated .c files)
instead of GitHub archive (only .pyx files → requires Cython run → fails).

Root cause from build logs:
  p4a downloads: https://github.com/kivy/kivy/archive/2.2.1.zip
  GitHub zip has NO .c files → clang-14: no such file 'kivy/_event.c'

Fix: use PyPI sdist Kivy-2.2.1.tar.gz which INCLUDES all .c files.
"""
from pythonforandroid.recipes.kivy import KivyRecipe


class KivyPyPIRecipe(KivyRecipe):
    url     = ("https://files.pythonhosted.org/packages/39/ed/"
               "d62cc0112107863899f88c5e59cd434082be6c3b1c423367ebf4e31c9c1a/"
               "Kivy-{version}.tar.gz")
    md5sum  = "576636a8a82be9e9b6cf15876f4e7c2f"
    version = "2.2.1"


recipe = KivyPyPIRecipe()
