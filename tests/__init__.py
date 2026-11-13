import os
import tempfile

# macOS keeps its temp folder behind a symlink (/var → /private/var) and pm prints resolved paths
tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
