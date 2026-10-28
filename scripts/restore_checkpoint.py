import os
import sys
from pathlib import Path
from podcast.checkpoint import restore

restore(Path(sys.argv[1]), os.environ['GITHUB_REPOSITORY'])
